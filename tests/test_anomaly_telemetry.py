"""Offline tests for the per-agent JSON telemetry store.

Covers round-trip persistence (incl. dict fields + cost-blind rows), ordering,
recency windowing at the boundary, task filtering (PER_TASK vs GLOBAL), tier
classification at every ladder boundary, current-job exclusion, the
``cost_samples`` cost-blind drop, and corrupt/missing-file tolerance.

Tier note: the store ports the Rust ``resolve_baseline_mode`` ladder faithfully
(per-task floor ≥3, global floor ≥2), which diverges from a naive "≥1" shape —
these tests assert the *Rust* behavior, including the thin-per-task fallback.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest

from agent_exchange.anomaly.telemetry import JsonTelemetryStore
from agent_exchange.anomaly.types import (
    DEFAULT_THRESHOLDS,
    BaselineMode,
    JobTelemetry,
    SampleSizeTier,
)

_DAY_MS = 86_400_000
_NOW = 1_000_000_000_000  # arbitrary fixed "now" in epoch ms (deterministic)


def _row(
    *,
    agent_id="agent-a",
    job_id="job-1",
    task="audit",
    started_at_ms=_NOW,
    model="gpt-5.5",
    est_cost_usd=0.01,
    latency_ms=1000,
    llm_call_count=2,
    total_input_tokens=400,
    tool_call_counts=None,
    model_call_counts=None,
):
    return JobTelemetry(
        agent_id=agent_id,
        job_id=job_id,
        task=task,
        started_at_ms=started_at_ms,
        model=model,
        est_cost_usd=est_cost_usd,
        latency_ms=latency_ms,
        llm_call_count=llm_call_count,
        total_input_tokens=total_input_tokens,
        tool_call_counts=tool_call_counts if tool_call_counts is not None else {},
        model_call_counts=model_call_counts if model_call_counts is not None else {},
    )


def _store(tmp_path):
    return JsonTelemetryStore(str(tmp_path / "telemetry.json"))


# --------------------------------------------------------------- round-trip


def test_record_then_rows_for_round_trip(tmp_path):
    store = _store(tmp_path)
    row = _row(
        tool_call_counts={"grep": 3, "read": 1},
        model_call_counts={"gpt-5.5": 2},
    )
    store.record(row)

    rows = store.rows_for("agent-a")
    assert len(rows) == 1
    got = rows[0]
    assert got.agent_id == "agent-a"
    assert got.job_id == "job-1"
    assert got.task == "audit"
    assert got.started_at_ms == _NOW
    assert got.model == "gpt-5.5"
    assert got.est_cost_usd == pytest.approx(0.01)
    assert got.latency_ms == 1000
    assert got.llm_call_count == 2
    assert got.total_input_tokens == 400
    # Dict fields survive the round-trip exactly.
    assert got.tool_call_counts == {"grep": 3, "read": 1}
    assert got.model_call_counts == {"gpt-5.5": 2}


def test_cost_blind_row_preserves_none(tmp_path):
    store = _store(tmp_path)
    store.record(_row(est_cost_usd=None))
    rows = store.rows_for("agent-a")
    assert len(rows) == 1
    # None must survive as None (never coerced to 0.0) — it's the cost-blind tell.
    assert rows[0].est_cost_usd is None


def test_empty_dict_fields_round_trip(tmp_path):
    store = _store(tmp_path)
    store.record(_row(tool_call_counts={}, model_call_counts={}))
    rows = store.rows_for("agent-a")
    assert rows[0].tool_call_counts == {}
    assert rows[0].model_call_counts == {}


def test_rows_for_unknown_agent_is_empty(tmp_path):
    store = _store(tmp_path)
    assert store.rows_for("nobody") == ()


def test_record_persists_across_store_instances(tmp_path):
    path = str(tmp_path / "telemetry.json")
    JsonTelemetryStore(path).record(_row(job_id="j1"))
    # A fresh instance reads the same file back.
    assert len(JsonTelemetryStore(path).rows_for("agent-a")) == 1


def test_multiple_agents_isolated(tmp_path):
    store = _store(tmp_path)
    store.record(_row(agent_id="a", job_id="j1"))
    store.record(_row(agent_id="b", job_id="j2"))
    assert len(store.rows_for("a")) == 1
    assert len(store.rows_for("b")) == 1
    assert store.rows_for("a")[0].job_id == "j1"


# --------------------------------------------------------------- ordering


def test_rows_for_sorted_by_started_at_ascending(tmp_path):
    store = _store(tmp_path)
    # Record out of order; rows_for must return ascending by started_at_ms.
    store.record(_row(job_id="late", started_at_ms=_NOW))
    store.record(_row(job_id="early", started_at_ms=_NOW - 5 * _DAY_MS))
    store.record(_row(job_id="mid", started_at_ms=_NOW - 2 * _DAY_MS))
    ids = [r.job_id for r in store.rows_for("agent-a")]
    assert ids == ["early", "mid", "late"]


# --------------------------------------------------------------- recency window


def test_recency_window_boundary_inclusive_and_exclusive(tmp_path):
    store = _store(tmp_path)
    # Exactly on the 30-day boundary: kept (delta == window_ms is inclusive).
    store.record(_row(job_id="on_edge", started_at_ms=_NOW - 30 * _DAY_MS))
    # One ms older than the boundary: dropped.
    store.record(_row(job_id="too_old", started_at_ms=_NOW - 30 * _DAY_MS - 1))
    # Comfortably inside.
    store.record(_row(job_id="fresh", started_at_ms=_NOW - 1 * _DAY_MS))

    bw = store.baseline(
        "agent-a",
        task="audit",
        mode=BaselineMode.GLOBAL,
        window_days=30,
        now_ms=_NOW,
    )
    kept = {r.job_id for r in bw.samples}
    assert kept == {"on_edge", "fresh"}
    assert bw.global_count == 2


# --------------------------------------------------------------- task filtering


def test_task_filter_per_task_vs_global_counts(tmp_path):
    store = _store(tmp_path)
    for i in range(4):
        store.record(_row(job_id=f"audit-{i}", task="audit", started_at_ms=_NOW - i))
    for i in range(2):
        store.record(_row(job_id=f"nda-{i}", task="nda", started_at_ms=_NOW - i))

    # GLOBAL: all 6 rows in the cohort, task_filter cleared.
    g = store.baseline(
        "agent-a", task="audit", mode=BaselineMode.GLOBAL, window_days=30, now_ms=_NOW
    )
    assert g.global_count == 6
    assert g.per_task_count == 4
    assert len(g.samples) == 6
    assert g.task_filter is None

    # PER_TASK: only the 4 "audit" rows in the cohort, task_filter set.
    pt = store.baseline(
        "agent-a", task="audit", mode=BaselineMode.PER_TASK, window_days=30, now_ms=_NOW
    )
    assert pt.global_count == 6
    assert pt.per_task_count == 4
    assert len(pt.samples) == 4
    assert pt.task_filter == "audit"
    assert all(s.task == "audit" for s in pt.samples)


# --------------------------------------------------------------- tier ladder


def test_tier_no_baseline_when_empty(tmp_path):
    store = _store(tmp_path)
    bw = store.baseline(
        "agent-a", task="audit", mode=BaselineMode.PER_TASK, window_days=30, now_ms=_NOW
    )
    assert bw.tier is SampleSizeTier.NO_BASELINE
    assert bw.samples == ()
    assert bw.global_count == 0
    assert bw.per_task_count == 0


def test_tier_single_per_task_row_falls_back_no_baseline(tmp_path):
    # Ported-Rust divergence from the brief's "1 -> PER_TASK_SIMPLE": the Rust
    # ladder requires per_task >= 3. One same-task row (and <2 global) stays
    # NO_BASELINE. Asserting the faithful Rust behavior.
    store = _store(tmp_path)
    store.record(_row(job_id="only", task="audit", started_at_ms=_NOW))
    bw = store.baseline(
        "agent-a", task="audit", mode=BaselineMode.PER_TASK, window_days=30, now_ms=_NOW
    )
    assert bw.tier is SampleSizeTier.NO_BASELINE


def test_tier_thin_per_task_falls_back_to_global_rolling(tmp_path):
    # per_task=1 (<3) but global=2 (>=2): the Rust ladder yields GLOBAL_ROLLING.
    store = _store(tmp_path)
    store.record(_row(job_id="a", task="audit", started_at_ms=_NOW))
    store.record(_row(job_id="b", task="nda", started_at_ms=_NOW - 1))
    bw = store.baseline(
        "agent-a", task="audit", mode=BaselineMode.PER_TASK, window_days=30, now_ms=_NOW
    )
    assert bw.per_task_count == 1
    assert bw.global_count == 2
    assert bw.tier is SampleSizeTier.GLOBAL_ROLLING


def test_tier_per_task_simple_at_3(tmp_path):
    store = _store(tmp_path)
    for i in range(3):
        store.record(_row(job_id=f"a{i}", task="audit", started_at_ms=_NOW - i))
    bw = store.baseline(
        "agent-a", task="audit", mode=BaselineMode.PER_TASK, window_days=30, now_ms=_NOW
    )
    assert bw.per_task_count == 3
    assert bw.tier is SampleSizeTier.PER_TASK_SIMPLE


def test_tier_per_task_bootstrap_at_exactly_bootstrap_min(tmp_path):
    n = DEFAULT_THRESHOLDS.bootstrap_min_runs  # 30
    store = _store(tmp_path)
    for i in range(n):
        store.record(_row(job_id=f"a{i}", task="audit", started_at_ms=_NOW - i))
    bw = store.baseline(
        "agent-a", task="audit", mode=BaselineMode.PER_TASK, window_days=30, now_ms=_NOW
    )
    assert bw.per_task_count == n
    assert bw.tier is SampleSizeTier.PER_TASK_BOOTSTRAP


def test_tier_one_below_bootstrap_is_simple(tmp_path):
    n = DEFAULT_THRESHOLDS.bootstrap_min_runs - 1  # 29
    store = _store(tmp_path)
    for i in range(n):
        store.record(_row(job_id=f"a{i}", task="audit", started_at_ms=_NOW - i))
    bw = store.baseline(
        "agent-a", task="audit", mode=BaselineMode.PER_TASK, window_days=30, now_ms=_NOW
    )
    assert bw.tier is SampleSizeTier.PER_TASK_SIMPLE


def test_tier_global_rolling_at_2(tmp_path):
    store = _store(tmp_path)
    store.record(_row(job_id="a", task="x", started_at_ms=_NOW))
    store.record(_row(job_id="b", task="y", started_at_ms=_NOW - 1))
    bw = store.baseline(
        "agent-a", task="z", mode=BaselineMode.GLOBAL, window_days=30, now_ms=_NOW
    )
    assert bw.global_count == 2
    assert bw.tier is SampleSizeTier.GLOBAL_ROLLING


def test_tier_global_single_row_is_no_baseline(tmp_path):
    # Global floor is >=2 (ported Rust); a single row stays NO_BASELINE.
    store = _store(tmp_path)
    store.record(_row(job_id="a", task="x", started_at_ms=_NOW))
    bw = store.baseline(
        "agent-a", task="z", mode=BaselineMode.GLOBAL, window_days=30, now_ms=_NOW
    )
    assert bw.global_count == 1
    assert bw.tier is SampleSizeTier.NO_BASELINE


def test_per_task_count_uses_thresholds_override(tmp_path):
    # A custom bootstrap_min lifts the bootstrap boundary.
    from dataclasses import replace

    store = _store(tmp_path)
    for i in range(5):
        store.record(_row(job_id=f"a{i}", task="audit", started_at_ms=_NOW - i))
    custom = replace(DEFAULT_THRESHOLDS, bootstrap_min_runs=5)
    bw = store.baseline(
        "agent-a",
        task="audit",
        mode=BaselineMode.PER_TASK,
        window_days=30,
        now_ms=_NOW,
        thresholds=custom,
    )
    assert bw.tier is SampleSizeTier.PER_TASK_BOOTSTRAP


# --------------------------------------------------------------- exclude job


def test_exclude_job_id_drops_current_job(tmp_path):
    store = _store(tmp_path)
    store.record(_row(job_id="current", task="audit", started_at_ms=_NOW))
    store.record(_row(job_id="prior", task="audit", started_at_ms=_NOW - 1))
    bw = store.baseline(
        "agent-a",
        task="audit",
        mode=BaselineMode.PER_TASK,
        window_days=30,
        now_ms=_NOW,
        exclude_job_id="current",
    )
    ids = {s.job_id for s in bw.samples}
    assert ids == {"prior"}
    assert bw.per_task_count == 1
    assert bw.global_count == 1


# --------------------------------------------------------------- cost_samples


def test_cost_samples_excludes_cost_blind_rows(tmp_path):
    store = _store(tmp_path)
    store.record(_row(job_id="priced1", task="audit", est_cost_usd=0.02, started_at_ms=_NOW))
    store.record(_row(job_id="blind", task="audit", est_cost_usd=None, started_at_ms=_NOW - 1))
    store.record(_row(job_id="priced2", task="audit", est_cost_usd=0.05, started_at_ms=_NOW - 2))
    bw = store.baseline(
        "agent-a", task="audit", mode=BaselineMode.PER_TASK, window_days=30, now_ms=_NOW
    )
    # Window holds all 3 rows, but cost_samples drops the cost-blind one.
    assert len(bw.samples) == 3
    assert sorted(bw.cost_samples) == pytest.approx([0.02, 0.05])


# --------------------------------------------------------------- file tolerance


def test_corrupt_file_tolerated_starts_fresh(tmp_path):
    path = tmp_path / "telemetry.json"
    path.write_text("{ this is not valid json", encoding="utf-8")
    store = JsonTelemetryStore(str(path))
    # Corrupt file -> empty read, no crash.
    assert store.rows_for("agent-a") == ()
    # And a subsequent record overwrites the garbage cleanly.
    store.record(_row(job_id="recovered"))
    assert len(store.rows_for("agent-a")) == 1


def test_non_dict_json_tolerated(tmp_path):
    path = tmp_path / "telemetry.json"
    path.write_text("[1, 2, 3]", encoding="utf-8")  # valid JSON, wrong shape
    store = JsonTelemetryStore(str(path))
    assert store.rows_for("agent-a") == ()


def test_missing_file_tolerated(tmp_path):
    store = JsonTelemetryStore(str(tmp_path / "nonexistent" / "telemetry.json"))
    assert store.rows_for("agent-a") == ()
    # First record creates parent dirs + file.
    store.record(_row())
    assert len(store.rows_for("agent-a")) == 1
