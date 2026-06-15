"""Tests for the per-run drift orchestration helper + the seeded sim cheater.

Covers:
  * ``evaluate_run_drift`` records one row per worker and returns one report each;
  * the seeded sim cheater scenario yields a CRITICAL model-swap+price-mismatch
    flag for the cheater and a clean (non-flagged) report for the other workers;
  * the helper is deterministic given a fixed ``now_ms``;
  * an empty / first-time worker (no baseline) yields a non-flagged, suppressed
    report (no crash);
  * the sim event generator emits the ``drift`` event with the documented shape
    for both the cheater and a clean worker.
"""

import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

# The server package (app.py / sim.py) lives under ../server, not in src.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))

import asyncio

import pytest

from agent_exchange.anomaly.run_drift import build_worker_telemetry, evaluate_run_drift
from agent_exchange.anomaly.telemetry import JsonTelemetryStore
from agent_exchange.anomaly.types import JobTelemetry
from agent_exchange.metrics import usdc

_KIND = "contract-audit"
_NOW = 1_700_000_000_000
_MS_PER_DAY = 86_400_000
_CONTRACT = "This contract caps liability and assigns IP. " * 30


def _seed_baseline(store: JsonTelemetryStore, worker: str, *, model: str,
                   cost: float, n: int = 12) -> None:
    """Seed ``n`` honest prior contract-audit jobs for ``worker`` on ``model``.

    Tokens mirror what ``build_worker_telemetry`` measures for the same document
    on the same model, so a clean worker that re-runs its baseline model lands on
    its own baseline (no false behavioral / prompt-length drift) — exactly the
    self-consistency the sim seeding establishes.
    """
    from agent_exchange.core.pricing import estimate_tokens

    tokens = estimate_tokens(_CONTRACT, model)
    for i in range(n):
        store.record(
            JobTelemetry(
                agent_id=worker, job_id=f"seed-{worker}-{i}", task=_KIND,
                started_at_ms=_NOW - (i + 1) * _MS_PER_DAY, model=model,
                est_cost_usd=cost, latency_ms=5000, llm_call_count=1,
                total_input_tokens=tokens, model_call_counts={model: 1},
            )
        )


# --------------------------------------------------------------------------- #
# build_worker_telemetry                                                       #
# --------------------------------------------------------------------------- #


def test_build_worker_telemetry_shape():
    row = build_worker_telemetry(
        worker="liability", model="gpt-4.1", kind=_KIND, job_id="job-1",
        now_ms=_NOW, contract_text=_CONTRACT, latency_ms=4200,
    )
    assert row.agent_id == "liability"
    assert row.job_id == "job-1"
    assert row.task == _KIND
    assert row.started_at_ms == _NOW
    assert row.model == "gpt-4.1"
    assert row.latency_ms == 4200
    assert row.llm_call_count == 1
    assert row.total_input_tokens > 0
    assert row.model_call_counts == {"gpt-4.1": 1}
    # gpt-4.1 is a priced model -> non-None cost.
    assert row.est_cost_usd is not None and row.est_cost_usd > 0.0


def test_build_worker_telemetry_unpriced_model_is_cost_blind():
    row = build_worker_telemetry(
        worker="x", model="totally-unknown-model", kind=_KIND, job_id="j",
        now_ms=_NOW, contract_text=_CONTRACT, latency_ms=1000,
    )
    assert row.est_cost_usd is None  # honest: unknown price -> cost-blind row


# --------------------------------------------------------------------------- #
# evaluate_run_drift — basic contract                                          #
# --------------------------------------------------------------------------- #


def test_records_one_row_per_worker_and_one_report_each(tmp_path):
    store = JsonTelemetryStore(str(tmp_path / "t.json"))
    workers = ["a", "b", "c"]
    reports = evaluate_run_drift(
        store, workers=workers,
        models={"a": "gpt-4.1", "b": "gpt-4o-mini", "c": "gpt-4.1"},
        bid_prices_atomic={}, kind=_KIND, job_id="job-1", now_ms=_NOW,
        contract_text=_CONTRACT, latency_ms=5000,
    )
    assert set(reports) == set(workers)
    # Exactly one row recorded per worker (the current run's row).
    for w in workers:
        assert len(store.rows_for(w)) == 1
        assert reports[w].job_id == "job-1"


def test_worker_without_a_model_is_skipped(tmp_path):
    store = JsonTelemetryStore(str(tmp_path / "t.json"))
    reports = evaluate_run_drift(
        store, workers=["a", "b"], models={"a": "gpt-4.1"},  # b has no model
        bid_prices_atomic={}, kind=_KIND, job_id="j", now_ms=_NOW,
        contract_text=_CONTRACT,
    )
    assert set(reports) == {"a"}
    assert store.rows_for("b") == ()


def test_first_time_worker_no_baseline_is_non_flagged(tmp_path):
    """A worker with no prior history -> NO_BASELINE -> suppressed, not flagged."""
    store = JsonTelemetryStore(str(tmp_path / "t.json"))
    reports = evaluate_run_drift(
        store, workers=["fresh"], models={"fresh": "gpt-4o-mini"},
        bid_prices_atomic={"fresh": usdc(0.04)}, kind=_KIND, job_id="j",
        now_ms=_NOW, contract_text=_CONTRACT,
    )
    r = reports["fresh"]
    assert r.flagged is False
    assert r.suppressed_reason == "no baseline"
    assert r.model_substitution is None  # nothing to compare against


# --------------------------------------------------------------------------- #
# evaluate_run_drift — the cheater vs clean catch                              #
# --------------------------------------------------------------------------- #


def test_cheater_fires_critical_clean_worker_does_not(tmp_path):
    store = JsonTelemetryStore(str(tmp_path / "t.json"))
    # Both workers historically ran the frontier model gpt-4.1.
    from agent_exchange.core.pricing import estimate_cost

    frontier_cost = estimate_cost("gpt-4.1", _CONTRACT)
    _seed_baseline(store, "cheater", model="gpt-4.1", cost=frontier_cost)
    _seed_baseline(store, "clean", model="gpt-4.1", cost=frontier_cost)

    reports = evaluate_run_drift(
        store,
        workers=["cheater", "clean"],
        # cheater quietly swaps to a cheap model; clean keeps its frontier model.
        models={"cheater": "gpt-4o-mini", "clean": "gpt-4.1"},
        # cheater bids a frontier price; clean bids 5x its real cost (< 8x floor).
        bid_prices_atomic={
            "cheater": usdc(0.04),
            "clean": usdc(round(frontier_cost * 5.0, 6)),
        },
        kind=_KIND, job_id="current", now_ms=_NOW, contract_text=_CONTRACT,
        latency_ms=5000,
    )

    ch = reports["cheater"]
    assert ch.flagged is True
    assert ch.overall_severity.value == "critical"
    assert ch.model_substitution is not None
    assert ch.model_substitution.model_switch is True
    assert ch.model_substitution.price_mismatch is True

    cl = reports["clean"]
    assert cl.flagged is False
    assert cl.model_substitution is not None
    assert cl.model_substitution.model_switch is False


def test_deterministic_given_fixed_now_ms(tmp_path):
    """Two identical runs (fresh stores, same now_ms) produce identical reports."""
    def run(path):
        store = JsonTelemetryStore(path)
        _seed_baseline(store, "w", model="gpt-4.1", cost=0.0016)
        reports = evaluate_run_drift(
            store, workers=["w"], models={"w": "gpt-4o-mini"},
            bid_prices_atomic={"w": usdc(0.04)}, kind=_KIND, job_id="cur",
            now_ms=_NOW, contract_text=_CONTRACT, latency_ms=5000,
        )
        r = reports["w"]
        ms = r.model_substitution
        return (r.flagged, r.overall_severity.value, ms.model_switch,
                ms.price_mismatch, round(ms.implied_overcharge_ratio, 6))

    a = run(str(tmp_path / "a.json"))
    b = run(str(tmp_path / "b.json"))
    assert a == b


# --------------------------------------------------------------------------- #
# Sim seeding + the SSE drift event shape                                      #
# --------------------------------------------------------------------------- #


def test_sim_seed_marks_confirmed_specialist_as_cheater():
    from sim import build_sim_scenario, _SCENARIOS

    scenario = build_sim_scenario(_KIND)
    assert scenario.drift_store is not None

    # The drifter must be a CONFIRMED-content specialist, NOT the seeded
    # fabricator — drift's whole value is catching a cheat the verifier misses,
    # so the two cheats land on two different nodes (no redundant double-catch).
    members = _SCENARIOS[_KIND]["members"]
    fabricator = next(m[5] for m in members if m[8] is None)
    confirmed = {m[5] for m in members if m[8] is not None}
    assert scenario.drift_cheater != fabricator
    assert scenario.drift_cheater in confirmed

    # The drifter quietly swapped to the cheap model; everyone else ran baseline.
    assert scenario.drift_models[scenario.drift_cheater] == "gpt-4o-mini"
    for w, m in scenario.drift_models.items():
        if w != scenario.drift_cheater:
            assert m == "gpt-4.1"
    # The store carries a seeded baseline for each specialist (>= 1 row).
    for w in scenario.drift_models:
        assert len(scenario.drift_store.rows_for(w)) >= 1


@pytest.mark.parametrize("kind", ["contract-audit", "nda-review"])
def test_sim_event_generator_emits_drift_events(kind):
    from app import run_job

    async def _collect():
        out = []
        async for ev, data in run_job(kind, document="", budget_usd=0.20,
                                      requested_mode="sim"):
            out.append((ev, data))
        return out

    events = _collect_sync(_collect)
    drifts = [d for n, d in events if n == "drift"]
    assert len(drifts) == 4  # one per specialist

    # Documented event shape present on every drift event.
    required = {
        "worker", "flagged", "severity", "model", "baseline_label",
        "model_switch", "price_mismatch", "overcharge_ratio",
        "cost_delta_pct", "latency_delta_pct", "summary",
    }
    for d in drifts:
        assert required <= set(d)

    # Exactly one CRITICAL cheater with both triggers; the rest are clean.
    cheaters = [d for d in drifts if d["flagged"]]
    assert len(cheaters) == 1
    ch = cheaters[0]
    assert ch["severity"] == "critical"
    assert ch["model_switch"] is True
    assert ch["price_mismatch"] is True
    assert ch["model"] == "gpt-4o-mini"
    assert "gpt-4.1 -> gpt-4o-mini" in ch["summary"]

    clean = [d for d in drifts if not d["flagged"]]
    assert len(clean) == 3
    for d in clean:
        assert d["severity"] == "info"
        assert d["model_switch"] is False
        assert d["summary"] == "behaving in-baseline"


def _collect_sync(coro_factory):
    """Run an async collector to completion (own loop, robust under pytest)."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro_factory())
    finally:
        loop.close()
