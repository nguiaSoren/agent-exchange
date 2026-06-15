"""Offline tests for the pure drift detectors in ``anomaly/drift.py``.

Covers each detector at its threshold boundaries (just-below-warn,
just-above-warn, above-critical), the fire-gates (min-sample, cost-blind,
PER_TASK-only), suppression-when-nothing-fires, the new model-substitution
triggers, and the ``evaluate`` aggregation incl. the NO_BASELINE short-circuit.

Fixtures are built by hand — these tests never touch the store/telemetry.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from agent_exchange.anomaly.drift import (  # noqa: E402
    compute_behavioral_drift,
    compute_cost_drift,
    compute_latency_drift,
    detect_model_substitution,
    evaluate,
)
from agent_exchange.anomaly.types import (  # noqa: E402
    BaselineMode,
    BaselineWindow,
    JobTelemetry,
    SampleSizeTier,
    Severity,
)

# --------------------------------------------------------------------------- #
# Fixture builders                                                             #
# --------------------------------------------------------------------------- #


def make_current(
    *,
    model: str = "gpt-4o",
    est_cost_usd: float | None = 1.0,
    latency_ms: int = 1000,
    llm_call_count: int = 0,
    total_input_tokens: int = 0,
    tool_call_counts: dict[str, int] | None = None,
    model_call_counts: dict[str, int] | None = None,
    task: str | None = "audit",
    agent_id: str = "agent-1",
    job_id: str = "job-cur",
) -> JobTelemetry:
    return JobTelemetry(
        agent_id=agent_id,
        job_id=job_id,
        task=task,
        started_at_ms=1000,
        model=model,
        est_cost_usd=est_cost_usd,
        latency_ms=latency_ms,
        llm_call_count=llm_call_count,
        total_input_tokens=total_input_tokens,
        tool_call_counts=tool_call_counts or {},
        model_call_counts=model_call_counts or {},
    )


def make_sample(
    *,
    model: str = "gpt-4o",
    est_cost_usd: float | None = 1.0,
    latency_ms: int = 1000,
    llm_call_count: int = 0,
    total_input_tokens: int = 0,
    tool_call_counts: dict[str, int] | None = None,
    model_call_counts: dict[str, int] | None = None,
    task: str | None = "audit",
) -> JobTelemetry:
    return JobTelemetry(
        agent_id="agent-1",
        job_id="job-base",
        task=task,
        started_at_ms=0,
        model=model,
        est_cost_usd=est_cost_usd,
        latency_ms=latency_ms,
        llm_call_count=llm_call_count,
        total_input_tokens=total_input_tokens,
        tool_call_counts=tool_call_counts or {},
        model_call_counts=model_call_counts or {},
    )


def make_window(
    samples: list[JobTelemetry],
    *,
    mode: BaselineMode = BaselineMode.PER_TASK,
    tier: SampleSizeTier = SampleSizeTier.PER_TASK_SIMPLE,
    task_filter: str | None = "audit",
    per_task_count: int | None = None,
    global_count: int | None = None,
) -> BaselineWindow:
    n = len(samples)
    return BaselineWindow(
        samples=tuple(samples),
        mode=mode,
        tier=tier,
        task_filter=task_filter,
        window_days=30,
        global_count=global_count if global_count is not None else n,
        per_task_count=per_task_count if per_task_count is not None else n,
    )


# --------------------------------------------------------------------------- #
# Cost drift                                                                   #
# --------------------------------------------------------------------------- #


def test_cost_just_below_warn_suppressed():
    # median = 1.0, current = 1.49 → +49% < 50% warn floor → suppressed (None).
    w = make_window([make_sample(est_cost_usd=c) for c in (0.8, 1.0, 1.2)])
    cur = make_current(est_cost_usd=1.49)
    assert compute_cost_drift(cur, w) is None


def test_cost_at_warn_boundary_is_warn():
    # median = 1.0, current = 1.5 → +50% exactly → WARN.
    w = make_window([make_sample(est_cost_usd=c) for c in (0.8, 1.0, 1.2)])
    cur = make_current(est_cost_usd=1.5)
    d = compute_cost_drift(cur, w)
    assert d is not None
    assert d.severity is Severity.WARN
    assert abs(d.delta_pct - 0.5) < 1e-9
    assert abs(d.baseline_median_usd - 1.0) < 1e-9


def test_cost_at_critical_boundary_is_critical():
    # median = 1.0, current = 2.0 → +100% → CRITICAL.
    w = make_window([make_sample(est_cost_usd=c) for c in (0.9, 1.0, 1.1)])
    cur = make_current(est_cost_usd=2.0)
    d = compute_cost_drift(cur, w)
    assert d is not None
    assert d.severity is Severity.CRITICAL
    assert abs(d.delta_pct - 1.0) < 1e-9


def test_cost_fire_gate_below_min_runs():
    # Only 2 priced samples < min_cost_runs (3) → None even with huge drift.
    w = make_window(
        [make_sample(est_cost_usd=1.0), make_sample(est_cost_usd=1.0)],
        per_task_count=2,
        global_count=2,
    )
    cur = make_current(est_cost_usd=10.0)
    assert compute_cost_drift(cur, w) is None


def test_cost_blind_current_suppressed():
    # current.est_cost_usd is None → cost-blind → None.
    w = make_window([make_sample(est_cost_usd=c) for c in (0.8, 1.0, 1.2)])
    cur = make_current(est_cost_usd=None)
    assert compute_cost_drift(cur, w) is None


def test_cost_blind_baseline_rows_excluded_from_median():
    # Cost-blind baseline rows must not skew the median (cost_samples drops them).
    # Priced rows: 1.0, 1.0, 1.0 → median 1.0; the None row is ignored. Still
    # ≥ min_cost_runs priced samples.
    w = make_window(
        [
            make_sample(est_cost_usd=1.0),
            make_sample(est_cost_usd=1.0),
            make_sample(est_cost_usd=1.0),
            make_sample(est_cost_usd=None),
        ]
    )
    cur = make_current(est_cost_usd=2.0)
    d = compute_cost_drift(cur, w)
    assert d is not None
    assert abs(d.baseline_median_usd - 1.0) < 1e-9


def test_cost_no_baseline_tier_suppressed():
    w = make_window(
        [make_sample(est_cost_usd=1.0)],
        tier=SampleSizeTier.NO_BASELINE,
    )
    cur = make_current(est_cost_usd=5.0)
    assert compute_cost_drift(cur, w) is None


def test_cost_improvement_not_flagged():
    # current below baseline → negative delta → suppressed.
    w = make_window([make_sample(est_cost_usd=c) for c in (1.0, 1.0, 1.0)])
    cur = make_current(est_cost_usd=0.5)
    assert compute_cost_drift(cur, w) is None


# --------------------------------------------------------------------------- #
# Latency drift                                                                #
# --------------------------------------------------------------------------- #


def test_latency_below_info_suppressed():
    # baseline p95 (max) = 1000, current = 1140 → +14% < 15% info → None.
    w = make_window([make_sample(latency_ms=ms) for ms in (800, 900, 1000)])
    cur = make_current(latency_ms=1140)
    assert compute_latency_drift(cur, w) is None


def test_latency_at_info_boundary_is_info():
    # p95 = 1000, current = 1150 → +15% exactly → INFO (present, not suppressed).
    w = make_window([make_sample(latency_ms=ms) for ms in (800, 900, 1000)])
    cur = make_current(latency_ms=1150)
    d = compute_latency_drift(cur, w)
    assert d is not None
    assert d.severity is Severity.INFO
    assert abs(d.delta_pct - 0.15) < 1e-9
    assert d.baseline_p95_ms == 1000


def test_latency_at_warn_boundary_is_warn():
    # p95 = 1000, current = 1500 → +50% → WARN.
    w = make_window([make_sample(latency_ms=ms) for ms in (800, 900, 1000)])
    cur = make_current(latency_ms=1500)
    d = compute_latency_drift(cur, w)
    assert d is not None
    assert d.severity is Severity.WARN


def test_latency_at_critical_boundary_is_critical():
    # p95 = 1000, current = 3000 → +200% → CRITICAL.
    w = make_window([make_sample(latency_ms=ms) for ms in (800, 900, 1000)])
    cur = make_current(latency_ms=3000)
    d = compute_latency_drift(cur, w)
    assert d is not None
    assert d.severity is Severity.CRITICAL
    assert abs(d.delta_pct - 2.0) < 1e-9


def test_latency_no_baseline_tier_suppressed():
    w = make_window(
        [make_sample(latency_ms=1000)],
        tier=SampleSizeTier.NO_BASELINE,
    )
    cur = make_current(latency_ms=9999)
    assert compute_latency_drift(cur, w) is None


# --------------------------------------------------------------------------- #
# Behavioral drift                                                             #
# --------------------------------------------------------------------------- #


def _behavioral_baseline(
    n: int,
    *,
    tool: int = 5,
    model: str = "gpt-4o",
    model_calls: int = 2,
    tokens_per_call: int = 100,
) -> list[JobTelemetry]:
    return [
        make_sample(
            model=model,
            tool_call_counts={"grep": tool},
            model_call_counts={model: model_calls},
            llm_call_count=model_calls,
            total_input_tokens=tokens_per_call * model_calls,
        )
        for _ in range(n)
    ]


def test_behavioral_global_mode_suppressed():
    w = make_window(
        _behavioral_baseline(15),
        mode=BaselineMode.GLOBAL,
        per_task_count=15,
    )
    cur = make_current(
        tool_call_counts={"grep": 5}, model_call_counts={"gpt-4o": 2}, llm_call_count=2
    )
    assert compute_behavioral_drift(cur, w) is None


def test_behavioral_below_min_runs_suppressed():
    # 5 per-task < 10 floor → silent even on a wild current shift.
    w = make_window(_behavioral_baseline(5), per_task_count=5)
    cur = make_current(
        tool_call_counts={"grep": 999},
        model_call_counts={"gpt-4o": 999},
        llm_call_count=999,
        total_input_tokens=999 * 9999,
    )
    assert compute_behavioral_drift(cur, w) is None


def test_behavioral_tool_usage_just_below_warn_suppressed():
    # baseline mean grep = 5, current = 6 → +20% < 40% → no tool shift; and
    # nothing else moves → whole block suppressed (None).
    w = make_window(_behavioral_baseline(12), per_task_count=12)
    cur = make_current(
        tool_call_counts={"grep": 6},
        model_call_counts={"gpt-4o": 2},
        llm_call_count=2,
        total_input_tokens=200,
    )
    assert compute_behavioral_drift(cur, w) is None


def test_behavioral_tool_usage_at_warn_boundary_fires():
    # baseline mean grep = 5, current = 7 → +40% exactly → tool shift fires.
    w = make_window(_behavioral_baseline(12), per_task_count=12)
    cur = make_current(
        tool_call_counts={"grep": 7},
        model_call_counts={"gpt-4o": 2},
        llm_call_count=2,
        total_input_tokens=200,
    )
    d = compute_behavioral_drift(cur, w)
    assert d is not None
    assert len(d.tool_usage_shifts) == 1
    assert d.tool_usage_shifts[0].tool == "grep"
    assert abs(d.tool_usage_shifts[0].delta_pct - 0.4) < 1e-9
    assert d.task_label == "audit"


def test_behavioral_new_tool_is_infinite_shift():
    # A tool absent from baseline appearing in current → +inf → always fires.
    w = make_window(_behavioral_baseline(12), per_task_count=12)
    cur = make_current(
        tool_call_counts={"grep": 5, "curl": 3},
        model_call_counts={"gpt-4o": 2},
        llm_call_count=2,
        total_input_tokens=200,
    )
    d = compute_behavioral_drift(cur, w)
    assert d is not None
    curl = next(s for s in d.tool_usage_shifts if s.tool == "curl")
    assert curl.delta_pct == float("inf")
    assert curl.baseline_mean_count == 0.0


def test_behavioral_model_shift_fires():
    # baseline 100% gpt-4o; current 100% claude → +/-100% share delta each.
    w = make_window(_behavioral_baseline(12), per_task_count=12)
    cur = make_current(
        model="claude-opus-4-8",
        tool_call_counts={"grep": 5},
        model_call_counts={"claude-opus-4-8": 2},
        llm_call_count=2,
        total_input_tokens=200,
    )
    d = compute_behavioral_drift(cur, w)
    assert d is not None
    assert len(d.model_shifts) == 2
    # Sorted by abs(delta) desc then name asc; both are 1.0 → name tiebreak.
    models = {r.model for r in d.model_shifts}
    assert models == {"gpt-4o", "claude-opus-4-8"}
    claude = next(r for r in d.model_shifts if r.model == "claude-opus-4-8")
    assert abs(claude.delta_pct - 1.0) < 1e-9
    assert abs(claude.current_share - 1.0) < 1e-9


def test_behavioral_prompt_length_shift_fires():
    # baseline avg = 100 tok/call; current = 200 → +100% → prompt-length fires.
    w = make_window(_behavioral_baseline(12), per_task_count=12)
    cur = make_current(
        tool_call_counts={"grep": 5},
        model_call_counts={"gpt-4o": 2},
        llm_call_count=2,
        total_input_tokens=400,  # 400 / 2 = 200 avg
    )
    d = compute_behavioral_drift(cur, w)
    assert d is not None
    assert d.prompt_length is not None
    assert abs(d.prompt_length.baseline_avg_tokens - 100.0) < 1e-9
    assert abs(d.prompt_length.current_avg_tokens - 200.0) < 1e-9
    assert abs(d.prompt_length.delta_pct - 1.0) < 1e-9


def test_behavioral_suppressed_when_nothing_fires():
    # Everything stable → all sub-blocks empty/None → None.
    w = make_window(_behavioral_baseline(12), per_task_count=12)
    cur = make_current(
        tool_call_counts={"grep": 5},
        model_call_counts={"gpt-4o": 2},
        llm_call_count=2,
        total_input_tokens=200,
    )
    assert compute_behavioral_drift(cur, w) is None


def test_behavioral_annotation_below_bootstrap():
    # per_task_count = 15 < 30 → annotation present.
    w = make_window(_behavioral_baseline(15), per_task_count=15)
    cur = make_current(
        tool_call_counts={"grep": 50},
        model_call_counts={"gpt-4o": 2},
        llm_call_count=2,
        total_input_tokens=200,
    )
    d = compute_behavioral_drift(cur, w)
    assert d is not None
    assert d.sample_size_annotation_n == 15


def test_behavioral_annotation_omitted_at_bootstrap():
    # per_task_count = 35 >= 30 → annotation suppressed.
    w = make_window(
        _behavioral_baseline(35),
        per_task_count=35,
        tier=SampleSizeTier.PER_TASK_BOOTSTRAP,
    )
    cur = make_current(
        tool_call_counts={"grep": 50},
        model_call_counts={"gpt-4o": 2},
        llm_call_count=2,
        total_input_tokens=200,
    )
    d = compute_behavioral_drift(cur, w)
    assert d is not None
    assert d.sample_size_annotation_n is None


# --------------------------------------------------------------------------- #
# Model substitution                                                          #
# --------------------------------------------------------------------------- #


def test_model_substitution_switch_only_is_warn():
    # Baseline ran gpt-4o; current runs an unseen model; no bid → switch only.
    w = make_window([make_sample(model="gpt-4o") for _ in range(5)])
    cur = make_current(model="llama-3-70b")
    sub = detect_model_substitution(cur, w)
    assert sub is not None
    assert sub.model_switch is True
    assert sub.price_mismatch is False
    assert sub.implied_overcharge_ratio is None
    assert sub.severity is Severity.WARN
    assert sub.flagged is True
    assert sub.baseline_models == ("gpt-4o",)


def test_model_substitution_price_mismatch_only_is_warn():
    # Same model as baseline (no switch), but bid implies a 10x overcharge.
    w = make_window([make_sample(model="gpt-4o") for _ in range(5)])
    cur = make_current(model="gpt-4o", est_cost_usd=1.0)
    # bid = $10 (10_000_000 atomic) vs $1 est → ratio 10 >= 8 → mismatch.
    sub = detect_model_substitution(cur, w, bid_price_atomic=10_000_000)
    assert sub is not None
    assert sub.model_switch is False
    assert sub.price_mismatch is True
    assert sub.implied_overcharge_ratio is not None
    assert abs(sub.implied_overcharge_ratio - 10.0) < 1e-9
    assert sub.severity is Severity.WARN
    assert sub.flagged is True


def test_model_substitution_both_triggers_is_critical():
    w = make_window([make_sample(model="gpt-4o") for _ in range(5)])
    cur = make_current(model="llama-3-70b", est_cost_usd=1.0)
    sub = detect_model_substitution(cur, w, bid_price_atomic=20_000_000)
    assert sub is not None
    assert sub.model_switch is True
    assert sub.price_mismatch is True
    assert sub.severity is Severity.CRITICAL
    assert sub.flagged is True


def test_model_substitution_neither_trigger_info_not_flagged():
    # Same model, modest bid (2x) → no triggers → INFO, flagged False.
    w = make_window([make_sample(model="gpt-4o") for _ in range(5)])
    cur = make_current(model="gpt-4o", est_cost_usd=1.0)
    sub = detect_model_substitution(cur, w, bid_price_atomic=2_000_000)
    assert sub is not None
    assert sub.model_switch is False
    assert sub.price_mismatch is False
    assert abs(sub.implied_overcharge_ratio - 2.0) < 1e-9
    assert sub.severity is Severity.INFO
    assert sub.flagged is False


def test_model_substitution_no_bid_path():
    # bid None → price-mismatch not computed; same model → no switch.
    w = make_window([make_sample(model="gpt-4o") for _ in range(5)])
    cur = make_current(model="gpt-4o")
    sub = detect_model_substitution(cur, w, bid_price_atomic=None)
    assert sub is not None
    assert sub.price_mismatch is False
    assert sub.implied_overcharge_ratio is None
    assert sub.severity is Severity.INFO
    assert sub.flagged is False


def test_model_substitution_no_baseline_no_bid_is_none():
    # Empty baseline + no bid → nothing to compare → None.
    w = make_window([], tier=SampleSizeTier.PER_TASK_SIMPLE, per_task_count=0)
    cur = make_current(model="gpt-4o")
    assert detect_model_substitution(cur, w) is None


def test_model_substitution_cheap_tier_strengthens_signal():
    # ratio 5 (< 8) on its own wouldn't fire, but the run model resolves to a
    # cheap tier (gpt-4o-mini, input $0.15 <= $1) and ratio >= 4 → strengthened.
    w = make_window([make_sample(model="gpt-4o-mini") for _ in range(5)])
    cur = make_current(model="gpt-4o-mini", est_cost_usd=1.0)
    sub = detect_model_substitution(cur, w, bid_price_atomic=5_000_000)
    assert sub is not None
    assert sub.model_switch is False
    assert sub.price_mismatch is True
    assert abs(sub.implied_overcharge_ratio - 5.0) < 1e-9


def test_model_substitution_zero_est_cost_ratio_none():
    # est_cost_usd == 0 → ratio undefined → no price mismatch, ratio None.
    w = make_window([make_sample(model="gpt-4o") for _ in range(5)])
    cur = make_current(model="gpt-4o", est_cost_usd=0.0)
    sub = detect_model_substitution(cur, w, bid_price_atomic=10_000_000)
    assert sub is not None
    assert sub.price_mismatch is False
    assert sub.implied_overcharge_ratio is None


# --------------------------------------------------------------------------- #
# evaluate (orchestrator)                                                      #
# --------------------------------------------------------------------------- #


def test_evaluate_no_baseline_suppressed():
    w = make_window([], tier=SampleSizeTier.NO_BASELINE, per_task_count=0, global_count=0)
    cur = make_current(est_cost_usd=99.0, latency_ms=99999)
    rep = evaluate(cur, w)
    assert rep.suppressed_reason == "no baseline"
    assert rep.flagged is False
    assert rep.overall_severity is Severity.INFO
    assert rep.cost is None
    assert rep.latency is None
    assert rep.behavioral is None
    assert rep.model_substitution is None
    assert rep.baseline_label == "(no baseline)"


def test_evaluate_clean_run_not_flagged():
    # 12 stable per-task rows, current matches baseline → nothing fires.
    w = make_window(_behavioral_baseline(12, model="gpt-4o"), per_task_count=12)
    cur = make_current(
        model="gpt-4o",
        est_cost_usd=1.0,
        latency_ms=1000,
        tool_call_counts={"grep": 5},
        model_call_counts={"gpt-4o": 2},
        llm_call_count=2,
        total_input_tokens=200,
    )
    rep = evaluate(cur, w, bid_price_atomic=2_000_000)
    assert rep.suppressed_reason is None
    assert rep.flagged is False
    assert rep.overall_severity is Severity.INFO
    assert rep.cost is None
    assert rep.latency is None
    assert rep.behavioral is None
    # model_substitution present (there is a baseline) but not flagged.
    assert rep.model_substitution is not None
    assert rep.model_substitution.flagged is False


def test_evaluate_aggregates_max_severity_and_flags():
    # Baseline rows priced at $1, latency 1000, model gpt-4o. Current: cost 3x
    # (CRITICAL), latency +50% (WARN), model switch + price mismatch (CRITICAL).
    base = [
        make_sample(
            model="gpt-4o",
            est_cost_usd=1.0,
            latency_ms=1000,
            tool_call_counts={"grep": 5},
            model_call_counts={"gpt-4o": 2},
            llm_call_count=2,
            total_input_tokens=200,
        )
        for _ in range(12)
    ]
    w = make_window(base, per_task_count=12)
    cur = make_current(
        model="llama-3-70b",
        est_cost_usd=3.0,
        latency_ms=1500,
        tool_call_counts={"grep": 5},
        model_call_counts={"llama-3-70b": 2},
        llm_call_count=2,
        total_input_tokens=200,
    )
    rep = evaluate(cur, w, bid_price_atomic=30_000_000)
    assert rep.cost is not None and rep.cost.severity is Severity.CRITICAL
    assert rep.latency is not None and rep.latency.severity is Severity.WARN
    # behavioral fires on the model-distribution shift (gpt-4o -> llama).
    assert rep.behavioral is not None
    assert rep.model_substitution is not None and rep.model_substitution.flagged
    assert rep.overall_severity is Severity.CRITICAL
    assert rep.flagged is True


def test_evaluate_warn_only_overall_warn():
    # Only latency moves into WARN; cost/behavioral/substitution quiet.
    base = [
        make_sample(
            model="gpt-4o",
            est_cost_usd=1.0,
            latency_ms=1000,
            tool_call_counts={"grep": 5},
            model_call_counts={"gpt-4o": 2},
            llm_call_count=2,
            total_input_tokens=200,
        )
        for _ in range(12)
    ]
    w = make_window(base, per_task_count=12)
    cur = make_current(
        model="gpt-4o",
        est_cost_usd=1.0,
        latency_ms=1500,  # +50% WARN
        tool_call_counts={"grep": 5},
        model_call_counts={"gpt-4o": 2},
        llm_call_count=2,
        total_input_tokens=200,
    )
    rep = evaluate(cur, w, bid_price_atomic=2_000_000)
    assert rep.cost is None
    assert rep.latency is not None and rep.latency.severity is Severity.WARN
    assert rep.behavioral is None
    assert rep.overall_severity is Severity.WARN
    assert rep.flagged is True
