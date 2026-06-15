"""Pure drift detectors + the top-level :func:`evaluate` orchestrator.

This module is the *detection* half of the anomaly package. It consumes a
*current* :class:`~agent_exchange.anomaly.types.JobTelemetry` row plus a
:class:`~agent_exchange.anomaly.types.BaselineWindow` (the agent's prior rows,
already filtered/tiered by :mod:`.telemetry`) and emits the drift-result types
defined in :mod:`.types`. It is **pure**: deterministic, no I/O, never reads the
store or the filesystem, never calls the network. Every input it needs is
passed in.

Faithful port (vs AgentScope ``agentscope-anomaly``):

* ``compute_cost_drift``      ← ``drift.rs::compute_cost_drift`` (§12.2) +
  ``shared_rules.rs::classify_cost_severity``.
* ``compute_latency_drift``   ← ``drift.rs::compute_latency_drift`` (§12.1) +
  ``shared_rules.rs::classify_latency_severity``. The Rust computes a per-tool
  p95; Agent Exchange has one job-level ``latency_ms`` per row, so the baseline
  "p95" here is the coarse max()-as-p95 surrogate over the row latencies (same
  "Phase 3B is coarse" caveat the Rust carries).
* ``compute_behavioral_drift`` ← ``drift.rs::compute_behavioral_drift`` (§12.3)
  and its three ported sub-signals (``compute_tool_usage_shifts``,
  ``compute_model_shifts``, ``compute_prompt_length_shift``). PER_TASK mode
  only, per §12.3.
* The **kind-shift** behavioral sub-signal (``compute_kind_shifts`` in the Rust)
  is intentionally NOT ported: Agent Exchange has no span-``kind`` taxonomy
  (there is no ``kind_counts`` field on :class:`JobTelemetry` — see the
  ``types.py`` module docstring). The block is skipped throughout; comments mark
  where it would have lived.
* ``detect_model_substitution`` is **new** (no AgentScope analog): the
  "frontier price, open-weight model" tell that pairs with the pricing table.

Determinism: every multi-row output is sorted by ``(abs(delta_pct) DESC,
name ASC)`` exactly as the Rust does (it sorts to escape ``HashSet`` iteration
non-determinism; ``dict`` iteration in Python is insertion-ordered, but we sort
anyway so the contract matches the Rust byte-for-byte).

Division safety: every baseline central value (median / mean / share / p95) is
guarded — a zero or non-positive baseline yields a suppressed (None / empty)
result, never a ``ZeroDivisionError``.
"""

from __future__ import annotations

from .types import (
    DEFAULT_THRESHOLDS,
    BaselineMode,
    BaselineWindow,
    BehavioralDrift,
    CostDrift,
    DriftReport,
    DriftThresholds,
    JobTelemetry,
    LatencyDrift,
    ModelShiftRow,
    ModelSubstitution,
    PromptLengthShift,
    SampleSizeTier,
    Severity,
    ToolUsageShift,
)

# --------------------------------------------------------------------------- #
# Small numeric helpers (ported from drift.rs::median / median_i64)            #
# --------------------------------------------------------------------------- #


def _median(values: tuple[float, ...] | list[float]) -> float:
    """Median of a sequence of floats. Empty → ``0.0`` (matches ``drift.rs``).

    For an even count the mean of the two central elements is returned; for an
    odd count the central element. Pure, allocates a sorted copy.
    """
    if not values:
        return 0.0
    s = sorted(values)
    n = len(s)
    if n % 2 == 0:
        return (s[n // 2 - 1] + s[n // 2]) / 2.0
    return s[n // 2]


def _p95_surrogate(latencies: tuple[int, ...] | list[int]) -> int:
    """Coarse p95 surrogate for small samples: the max of the row latencies.

    Ported intent from ``drift.rs::compute_latency_drift`` — the Rust notes
    "Phase 3B is coarse; F-BENCH tightens this" and uses a sample aggregate as a
    per-tool baseline. Agent Exchange has one job-level latency per row, so the
    baseline "p95" is the max over the window's row latencies — a conservative
    surrogate that won't false-fire on a single slow run while a real p95
    estimator is deferred. Empty → ``0``.
    """
    if not latencies:
        return 0
    return max(latencies)


# --------------------------------------------------------------------------- #
# Cost drift (§12.2)                                                           #
# --------------------------------------------------------------------------- #


def compute_cost_drift(
    current: JobTelemetry,
    baseline: BaselineWindow,
    thresholds: DriftThresholds = DEFAULT_THRESHOLDS,
) -> CostDrift | None:
    """Recent cost vs the baseline MEDIAN of priced cost samples (§12.2).

    Ported from ``drift.rs::compute_cost_drift`` + ``classify_cost_severity``.
    The cost classifier has no INFO threshold — INFO is "below WARN" — so this
    *suppresses* the INFO tier (returns ``None`` when ``delta_pct`` is below the
    WARN floor). Only a WARN-or-worse cost move is reported, matching the
    detector-returns-Optional contract.

    Parameters
    ----------
    current:
        The current job's telemetry row.
    baseline:
        The agent's prior window. ``baseline.cost_samples`` (priced rows only)
        is the comparison population.
    thresholds:
        Drift thresholds; defaults to the AgentScope-verified defaults.

    Returns
    -------
    CostDrift | None
        ``None`` (silent) when any fire-gate fails: ``NO_BASELINE`` tier, fewer
        than ``min_cost_runs`` priced samples, a cost-blind current row
        (``est_cost_usd is None``), a non-positive baseline median, or a
        ``delta_pct`` below the WARN floor. Otherwise a :class:`CostDrift` whose
        ``severity`` is WARN (``>= cost_warn_pct``) or CRITICAL
        (``>= cost_critical_pct``).

    Notes
    -----
    ``delta_pct = (current - median) / median`` — signed (a cost *drop* yields a
    negative delta, which is below the WARN floor and therefore suppressed; we
    never flag an improvement).
    """
    if baseline.tier is SampleSizeTier.NO_BASELINE:
        return None

    samples = baseline.cost_samples  # priced rows only (cost-blind dropped)
    # Fire-gate: need ≥ min_cost_runs priced samples AND a priced current row.
    if len(samples) < thresholds.min_cost_runs:
        return None
    if current.est_cost_usd is None:
        return None

    baseline_median = _median(samples)
    if baseline_median <= 0.0:
        # Pathological baseline (all-zero / negative) — treat as silent.
        return None

    recent = current.est_cost_usd
    delta_pct = (recent - baseline_median) / baseline_median

    severity = _classify_cost_severity(delta_pct, thresholds)
    # Suppress the INFO tier (below the WARN floor) per the Optional contract.
    if severity is Severity.INFO:
        return None

    return CostDrift(
        current_usd=recent,
        baseline_median_usd=baseline_median,
        delta_pct=delta_pct,
        severity=severity,
    )


def _classify_cost_severity(delta_pct: float, t: DriftThresholds) -> Severity:
    """Port of ``shared_rules.rs::classify_cost_severity``.

    ``>= cost_critical_pct`` → CRITICAL; else ``>= cost_warn_pct`` → WARN; else
    INFO (negative/mild drift; improvements are never flagged as warnings).
    """
    if delta_pct >= t.cost_critical_pct:
        return Severity.CRITICAL
    if delta_pct >= t.cost_warn_pct:
        return Severity.WARN
    return Severity.INFO


# --------------------------------------------------------------------------- #
# Latency drift (§12.1)                                                        #
# --------------------------------------------------------------------------- #


def compute_latency_drift(
    current: JobTelemetry,
    baseline: BaselineWindow,
    thresholds: DriftThresholds = DEFAULT_THRESHOLDS,
) -> LatencyDrift | None:
    """Current ``latency_ms`` vs the baseline p95 of row latencies (§12.1).

    Ported from ``drift.rs::compute_latency_drift`` + ``classify_latency_severity``.
    Unlike cost, latency has a real INFO tier (``latency_info_pct``); this
    suppresses only *below* that INFO floor, returning a :class:`LatencyDrift`
    for INFO/WARN/CRITICAL.

    Parameters
    ----------
    current:
        The current job's telemetry row (``latency_ms``).
    baseline:
        The agent's prior window; the p95 surrogate is the max of the window's
        row latencies (see :func:`_p95_surrogate` — the same coarse Phase-3B
        approach the Rust documents for small samples).
    thresholds:
        Drift thresholds; defaults to the AgentScope-verified defaults.

    Returns
    -------
    LatencyDrift | None
        ``None`` when the ``NO_BASELINE`` tier holds, the window has no rows, the
        baseline p95 is non-positive, or ``delta_pct`` is below the INFO floor.
        Otherwise a :class:`LatencyDrift` (INFO / WARN / CRITICAL).
    """
    if baseline.tier is SampleSizeTier.NO_BASELINE:
        return None
    if baseline.n == 0:
        return None

    baseline_p95 = _p95_surrogate([s.latency_ms for s in baseline.samples])
    if baseline_p95 <= 0:
        return None

    delta_pct = (current.latency_ms - baseline_p95) / baseline_p95
    severity = _classify_latency_severity(delta_pct, thresholds)
    # Suppress below the INFO floor (a normal / improved latency).
    if delta_pct < thresholds.latency_info_pct:
        return None

    return LatencyDrift(
        current_ms=current.latency_ms,
        baseline_p95_ms=baseline_p95,
        delta_pct=delta_pct,
        severity=severity,
    )


def _classify_latency_severity(delta_pct: float, t: DriftThresholds) -> Severity:
    """Port of ``shared_rules.rs::classify_latency_severity``.

    ``>= latency_critical_pct`` → CRITICAL; else ``>= latency_warn_pct`` → WARN;
    else INFO. (The caller separately suppresses anything below
    ``latency_info_pct``.)
    """
    if delta_pct >= t.latency_critical_pct:
        return Severity.CRITICAL
    if delta_pct >= t.latency_warn_pct:
        return Severity.WARN
    return Severity.INFO


# --------------------------------------------------------------------------- #
# Behavioral drift (§12.3) — PER_TASK only                                     #
# --------------------------------------------------------------------------- #


def compute_behavioral_drift(
    current: JobTelemetry,
    baseline: BaselineWindow,
    thresholds: DriftThresholds = DEFAULT_THRESHOLDS,
) -> BehavioralDrift | None:
    """Aggregate behavioral drift (§12.3): tool-usage, model-distribution,
    prompt-length. PER_TASK mode ONLY.

    Ported from ``drift.rs::compute_behavioral_drift``. Three of the four Rust
    sub-signals port; the **kind-shift** sub-signal is omitted (Agent Exchange
    has no span-kind taxonomy — there is no ``kind_counts`` field).

    Fire-gates (both must pass, else ``None``):

    * PER_TASK mode (GLOBAL is rejected — mixing dissimilar workloads is noise).
    * ``baseline.per_task_count >= thresholds.min_behavioral_runs`` (default 10).

    Suppression: if every sub-block is empty/None (nothing crossed
    ``behavioral_warn_pct``), the whole block is suppressed → ``None``
    (``drift.rs`` §17.4 line-804 rule).

    Parameters
    ----------
    current:
        The current job's telemetry row.
    baseline:
        The agent's prior window (PER_TASK-filtered).
    thresholds:
        Drift thresholds; defaults to the AgentScope-verified defaults.

    Returns
    -------
    BehavioralDrift | None
        ``None`` when a fire-gate fails or nothing crossed threshold. Otherwise
        a :class:`BehavioralDrift` carrying the non-empty sub-blocks. Its
        ``sample_size_annotation_n`` is ``per_task_count`` when below
        ``bootstrap_min_runs`` (default 30), else ``None``; ``task_label`` is
        ``baseline.task_filter``.
    """
    # PER_TASK ONLY — GLOBAL mode rejected per §12.3.
    if baseline.mode is not BaselineMode.PER_TASK:
        return None
    # §12.3 silent floor: < min_behavioral_runs (default 10) per-task samples.
    if baseline.per_task_count < thresholds.min_behavioral_runs:
        return None

    tool_usage_shifts = _compute_tool_usage_shifts(current, baseline, thresholds)
    model_shifts = _compute_model_shifts(current, baseline, thresholds)
    prompt_length = _compute_prompt_length_shift(current, baseline, thresholds)
    # NOTE: kind-shift sub-signal intentionally omitted (no span-kind taxonomy
    # in Agent Exchange; see module docstring + types.py).

    # §17.4 line-804 suppression: no sub-block fired → suppress the whole block.
    if not tool_usage_shifts and not model_shifts and prompt_length is None:
        return None

    # "(based on N runs)" annotation fires below the bootstrap-CI threshold (30).
    sample_size_annotation_n = (
        baseline.per_task_count
        if baseline.per_task_count < thresholds.bootstrap_min_runs
        else None
    )

    return BehavioralDrift(
        task_label=baseline.task_filter or "",
        tool_usage_shifts=tool_usage_shifts,
        model_shifts=model_shifts,
        prompt_length=prompt_length,
        sample_size_annotation_n=sample_size_annotation_n,
    )


def _compute_tool_usage_shifts(
    current: JobTelemetry,
    baseline: BaselineWindow,
    thresholds: DriftThresholds,
) -> tuple[ToolUsageShift, ...]:
    """Per-tool current count vs baseline MEAN count (§12.3 signal 1).

    Ported from ``drift.rs::compute_tool_usage_shifts``. Baseline mean = total
    tool calls across the window / number of rows. A tool fires when
    ``abs(delta_pct) >= behavioral_warn_pct``; a tool that appears in the
    current run but never in the baseline (baseline mean 0) is a +∞ shift and
    always fires. Sorted by ``(abs(delta_pct) DESC, tool ASC)``.
    """
    n = float(baseline.n)
    if n <= 0.0:
        return ()

    baseline_totals: dict[str, int] = {}
    for sample in baseline.samples:
        for tool, count in sample.tool_call_counts.items():
            baseline_totals[tool] = baseline_totals.get(tool, 0) + count

    all_tools = set(baseline_totals) | set(current.tool_call_counts)

    out: list[ToolUsageShift] = []
    for tool in all_tools:
        baseline_mean = baseline_totals.get(tool, 0) / n
        recent_count = current.tool_call_counts.get(tool, 0)
        if baseline_mean <= 0.0 and recent_count <= 0:
            continue
        if baseline_mean > 0.0:
            delta_pct = (recent_count - baseline_mean) / baseline_mean
        else:
            # New tool appeared in the current run; +∞ shift → always fires.
            delta_pct = float("inf")
        if abs(delta_pct) >= thresholds.behavioral_warn_pct:
            out.append(
                ToolUsageShift(
                    tool=tool,
                    current_count=recent_count,
                    baseline_mean_count=baseline_mean,
                    delta_pct=delta_pct,
                )
            )

    out.sort(key=lambda s: (-abs(s.delta_pct), s.tool))
    return tuple(out)


def _compute_model_shifts(
    current: JobTelemetry,
    baseline: BaselineWindow,
    thresholds: DriftThresholds,
) -> tuple[ModelShiftRow, ...]:
    """Per-model share of LLM calls, current vs baseline (§12.3 signal 2).

    Ported from ``drift.rs::compute_model_shifts``. ``share`` = a model's call
    count / the total LLM calls. A model fires when the *share delta*
    (``recent_share - baseline_share``) has ``abs >= behavioral_warn_pct``.
    Both totals must be positive (guarded), else no shifts. Sorted by
    ``(abs(delta_pct) DESC, model ASC)``.
    """
    baseline_total = sum(s.llm_call_count for s in baseline.samples)
    current_total = current.llm_call_count
    if baseline_total <= 0 or current_total <= 0:
        return ()

    baseline_totals: dict[str, int] = {}
    for sample in baseline.samples:
        for model, count in sample.model_call_counts.items():
            baseline_totals[model] = baseline_totals.get(model, 0) + count

    all_models = set(baseline_totals) | set(current.model_call_counts)

    out: list[ModelShiftRow] = []
    for model in all_models:
        baseline_share = baseline_totals.get(model, 0) / baseline_total
        recent_share = current.model_call_counts.get(model, 0) / current_total
        delta_pct = recent_share - baseline_share
        if abs(delta_pct) >= thresholds.behavioral_warn_pct:
            out.append(
                ModelShiftRow(
                    model=model,
                    current_share=recent_share,
                    baseline_share=baseline_share,
                    delta_pct=delta_pct,
                )
            )

    out.sort(key=lambda r: (-abs(r.delta_pct), r.model))
    return tuple(out)


def _compute_prompt_length_shift(
    current: JobTelemetry,
    baseline: BaselineWindow,
    thresholds: DriftThresholds,
) -> PromptLengthShift | None:
    """Average prompt length (input tokens / LLM call) vs baseline (§12.3 sig 4).

    Ported from ``drift.rs::compute_prompt_length_shift``. Baseline average =
    total input tokens across the window / total LLM calls across the window
    (pooled, matching the Rust). Fires when
    ``abs(delta_pct) >= behavioral_warn_pct``. Guards a zero current LLM count,
    a zero baseline call total, and a non-positive baseline average.
    """
    baseline_total_tokens = sum(s.total_input_tokens for s in baseline.samples)
    baseline_total_calls = sum(s.llm_call_count for s in baseline.samples)
    if baseline_total_calls <= 0 or current.llm_call_count <= 0:
        return None

    baseline_avg = baseline_total_tokens / baseline_total_calls
    if baseline_avg <= 0.0:
        return None

    # current.avg_prompt_tokens is float | None; the guard above ensures it is
    # non-None here, but we recompute defensively to keep the function total.
    recent_avg = current.total_input_tokens / current.llm_call_count
    delta_pct = (recent_avg - baseline_avg) / baseline_avg
    if abs(delta_pct) >= thresholds.behavioral_warn_pct:
        return PromptLengthShift(
            current_avg_tokens=recent_avg,
            baseline_avg_tokens=baseline_avg,
            delta_pct=delta_pct,
        )
    return None


# --------------------------------------------------------------------------- #
# Model substitution — NEW (no AgentScope analog)                             #
# --------------------------------------------------------------------------- #

# A normal verifier+worker markup over the raw model cost is small (the bid
# covers compute + margin, not a 10× spread). A bid that implies the buyer is
# paying for a far pricier model than the agent actually ran is the
# "frontier price, open-weight model" tell. We flag when the bid is ≥ 8× the
# estimated cost of the model actually run: well above any legitimate margin,
# yet not so tight that ordinary overhead trips it. Tunable; chosen as a
# principled constant rather than a config field to keep this signal
# self-contained (the threshold is documented, not magic).
_PRICE_MISMATCH_RATIO = 8.0

# Cheap-tier ceiling (USD per Mtok input) used as a corroborating cross-check
# against the pricing table: if the *run* model resolves to at-or-below this
# input price while the bid implies frontier spend, the price-mismatch signal
# is strengthened. Frontier 4.x/GPT-5.x inputs sit well above this (≥ $2/Mtok).
_CHEAP_TIER_INPUT_PER_MTOK = 1.0


def detect_model_substitution(
    current: JobTelemetry,
    baseline: BaselineWindow,
    *,
    bid_price_atomic: int | None = None,
    thresholds: DriftThresholds = DEFAULT_THRESHOLDS,
) -> ModelSubstitution | None:
    """The "frontier price, open-weight model" tell (NEW — no AgentScope analog).

    Two independent triggers, either of which sets ``flagged``:

    * ``model_switch`` — the baseline is non-empty (``baseline.models_seen``)
      AND the current model was never seen in it (a quiet model swap).
    * ``price_mismatch`` — only computable when ``bid_price_atomic`` is given
      AND ``current.est_cost_usd`` is not None. The bid (USDC atomic, 6dp) is
      converted to USD and divided by the estimated cost of the model actually
      run to get ``implied_overcharge_ratio``. It flags when that ratio is
      implausibly high (``>= _PRICE_MISMATCH_RATIO`` = 8×) — the price implies a
      far pricier model than was run. The signal is *strengthened* (but not
      gated) when the run model resolves to a cheap-tier price in the pricing
      table while the bid implies frontier spend.

    Severity: CRITICAL when both trigger, WARN when exactly one, INFO when
    neither (returned with ``flagged=False`` so callers can show "checked, OK").

    Parameters
    ----------
    current:
        The current job's telemetry row (``model``, ``est_cost_usd``).
    baseline:
        The agent's prior window (``models_seen`` is the model-switch reference).
    bid_price_atomic:
        The accepted bid in USDC atomic units (6dp). ``None`` disables the
        price-mismatch trigger (then ``implied_overcharge_ratio`` is ``None``).
    thresholds:
        Accepted for signature symmetry with the other detectors (unused here;
        the substitution thresholds are this module's documented constants).

    Returns
    -------
    ModelSubstitution | None
        ``None`` when there is no baseline to compare against
        (``baseline.models_seen`` is empty) AND no price-mismatch could be
        computed — there is nothing to say. Otherwise a :class:`ModelSubstitution`
        (``flagged`` reflects whether either trigger fired).

    Notes
    -----
    Pure: the pricing cross-check reads the in-memory ``PRICE_PER_MTOK`` table
    via :func:`agent_exchange.core.pricing.price_for`; no network call.
    """
    baseline_models = tuple(sorted(baseline.models_seen))
    has_baseline = len(baseline_models) > 0

    # ── Trigger 1: model switch ──────────────────────────────────────────
    model_switch = has_baseline and current.model not in baseline.models_seen

    # ── Trigger 2: price mismatch ────────────────────────────────────────
    price_mismatch = False
    implied_overcharge_ratio: float | None = None
    can_price = bid_price_atomic is not None and current.est_cost_usd is not None
    if can_price and current.est_cost_usd is not None and bid_price_atomic is not None:
        bid_price_usd = bid_price_atomic / 1_000_000  # USDC 6dp → USD
        est = current.est_cost_usd
        if est > 0.0:
            implied_overcharge_ratio = bid_price_usd / est
            price_mismatch = implied_overcharge_ratio >= _PRICE_MISMATCH_RATIO
            # Corroborating cross-check: a cheap-tier run model under a
            # frontier-implying bid strengthens (but does not gate) the signal.
            if not price_mismatch and implied_overcharge_ratio >= (
                _PRICE_MISMATCH_RATIO / 2.0
            ):
                if _resolves_to_cheap_tier(current.model):
                    price_mismatch = True
        # est == 0.0 → ratio undefined; leave implied_overcharge_ratio None.

    # Nothing to compare against on either axis → silent.
    if not has_baseline and not can_price:
        return None

    triggers = int(model_switch) + int(price_mismatch)
    if triggers >= 2:
        severity = Severity.CRITICAL
    elif triggers == 1:
        severity = Severity.WARN
    else:
        severity = Severity.INFO

    return ModelSubstitution(
        current_model=current.model,
        baseline_models=baseline_models,
        model_switch=model_switch,
        price_mismatch=price_mismatch,
        implied_overcharge_ratio=implied_overcharge_ratio,
        severity=severity,
    )


def _resolves_to_cheap_tier(model: str) -> bool:
    """True when ``model`` resolves to a cheap-tier input price in the table.

    Reads :data:`agent_exchange.core.pricing.PRICE_PER_MTOK` via ``price_for``
    (in-memory, no network). Unknown models resolve to ``None`` and return
    ``False`` (we don't strengthen the signal on a model we can't price).
    """
    from ..core.pricing import price_for

    price = price_for(model)
    if price is None:
        return False
    return price.input <= _CHEAP_TIER_INPUT_PER_MTOK


# --------------------------------------------------------------------------- #
# Orchestrator                                                                 #
# --------------------------------------------------------------------------- #


def evaluate(
    current: JobTelemetry,
    baseline: BaselineWindow,
    *,
    bid_price_atomic: int | None = None,
    thresholds: DriftThresholds = DEFAULT_THRESHOLDS,
) -> DriftReport:
    """Run all four detectors and assemble a :class:`DriftReport`.

    Parameters
    ----------
    current:
        The current job's telemetry row.
    baseline:
        The agent's prior window.
    bid_price_atomic:
        Accepted bid (USDC atomic, 6dp) for the model-substitution price check;
        ``None`` disables that trigger.
    thresholds:
        Drift thresholds; defaults to the AgentScope-verified defaults.

    Returns
    -------
    DriftReport
        When ``baseline.tier`` is ``NO_BASELINE``: an informational report with
        ``suppressed_reason="no baseline"``, ``flagged=False``,
        ``overall_severity=INFO`` and all sub-fields ``None`` (nothing to compare
        against). Otherwise each detector is run and the report carries whichever
        sub-signals fired. ``overall_severity`` is the max severity across the
        present sub-signals (INFO when none fired); ``flagged`` is True when any
        present sub-signal reached WARN or worse (the model-substitution signal
        counts only when its ``.flagged`` is True). ``baseline_label`` is
        ``baseline.label``.
    """
    if baseline.tier is SampleSizeTier.NO_BASELINE:
        return DriftReport(
            agent_id=current.agent_id,
            job_id=current.job_id,
            baseline_label=baseline.label,
            overall_severity=Severity.INFO,
            flagged=False,
            cost=None,
            latency=None,
            behavioral=None,
            model_substitution=None,
            suppressed_reason="no baseline",
        )

    cost = compute_cost_drift(current, baseline, thresholds)
    latency = compute_latency_drift(current, baseline, thresholds)
    behavioral = compute_behavioral_drift(current, baseline, thresholds)
    model_substitution = detect_model_substitution(
        current, baseline, bid_price_atomic=bid_price_atomic, thresholds=thresholds
    )

    # Collect severities of the present, *meaningful* sub-signals.
    # Behavioral has no single severity field — when present it crossed the WARN
    # shift threshold, so it counts as WARN for aggregation.
    severities: list[Severity] = []
    if cost is not None:
        severities.append(cost.severity)
    if latency is not None:
        severities.append(latency.severity)
    if behavioral is not None:
        severities.append(Severity.WARN)
    if model_substitution is not None and model_substitution.flagged:
        severities.append(model_substitution.severity)

    overall_severity = (
        max(severities, key=lambda s: s.rank) if severities else Severity.INFO
    )
    flagged = any(s.rank >= Severity.WARN.rank for s in severities)

    return DriftReport(
        agent_id=current.agent_id,
        job_id=current.job_id,
        baseline_label=baseline.label,
        overall_severity=overall_severity,
        flagged=flagged,
        cost=cost,
        latency=latency,
        behavioral=behavioral,
        model_substitution=model_substitution,
        suppressed_reason=None,
    )


__all__ = [
    "compute_cost_drift",
    "compute_latency_drift",
    "compute_behavioral_drift",
    "detect_model_substitution",
    "evaluate",
]
