"""Schema seam for the anomaly package — shapes shared by store + detectors.

This module is the *contract* between :mod:`.telemetry` (which produces and
aggregates rows) and :mod:`.drift` (which consumes a baseline + a current row
and emits drift findings). It holds only data: frozen dataclasses, enums, and
the threshold table. No I/O, no detection logic — both of those live downstream
so the two can be built and evolved independently against these fixed shapes.

Faithful-port notes (vs AgentScope ``agentscope-anomaly``):

* ``JobTelemetry`` collapses AgentScope's ``RunSummary`` + ``BaselineSample``
  into one per-``(agent, job)`` row — Agent Exchange has no span DB, so the
  unit of observation is a job, not a trace.
* ``est_cost_usd`` is ``float | None``: ``None`` means a missing-price model so
  the row is *cost-blind* and must NOT skew the cost baseline (AgentScope's
  ``total_cost_usd: Option<f64>`` rule, preserved verbatim in spirit).
* The **kind-shift** behavioral signal is intentionally NOT ported: Agent
  Exchange has no span ``kind`` taxonomy, so that detector has no analog. The
  other three behavioral signals (tool-usage, model-distribution, prompt-length)
  do port.
* ``ModelSubstitution`` is **new** to Agent Exchange (no AgentScope analog): the
  price-vs-model mismatch signal that pairs with the pricing table (#2) — the
  "frontier price, open-weight model" tell.

Money is USDC atomic ints (6dp) everywhere a price crosses the marketplace
boundary, matching :mod:`agent_exchange.market.schema`. Costs derived from the
pricing table stay as ``float`` USD (estimates, never settled amounts).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

# --------------------------------------------------------------------------- #
# Enums (ported from agentscope-anomaly/src/shared_rules.rs)                   #
# --------------------------------------------------------------------------- #


class BaselineMode(str, Enum):
    """Which population a current row is compared against.

    ``PER_TASK`` compares an agent only against its own prior jobs of the *same*
    task/specialty (the high-signal mode; the only mode behavioral drift runs
    in, per AgentScope §12.3). ``GLOBAL`` compares against all of the agent's
    prior jobs regardless of task — a coarse fallback used for cost/latency when
    per-task samples are too thin.
    """

    PER_TASK = "per_task"
    GLOBAL = "global"


class SampleSizeTier(str, Enum):
    """Confidence tier for a baseline window, set by how many samples it holds.

    Mirrors AgentScope's tiering so the buyer-facing label can read
    ``(n=N task)`` etc. ``NO_BASELINE`` suppresses all drift (nothing to compare
    against). ``PER_TASK_BOOTSTRAP`` is the high-confidence tier where a
    bootstrap CI would apply; below it the finding carries a "based on N runs"
    caveat.
    """

    NO_BASELINE = "no_baseline"
    GLOBAL_ROLLING = "global_rolling"
    PER_TASK_SIMPLE = "per_task_simple"
    PER_TASK_BOOTSTRAP = "per_task_bootstrap"


class Severity(str, Enum):
    """Drift severity, ordered. ``INFO`` < ``WARN`` < ``CRITICAL``."""

    INFO = "info"
    WARN = "warn"
    CRITICAL = "critical"

    @property
    def rank(self) -> int:
        return {"info": 0, "warn": 1, "critical": 2}[self.value]


# --------------------------------------------------------------------------- #
# Thresholds (ported defaults from shared_rules.rs::DriftThresholds::default)  #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class DriftThresholds:
    """Tunable thresholds for the drift detectors.

    Defaults are AgentScope's verified defaults (``DriftThresholds::default()``),
    carried over verbatim so the ported detectors behave identically out of the
    box. ``*_pct`` values are fractional deltas vs the baseline central value
    (e.g. ``cost_warn_pct=0.50`` → +50% over baseline median = WARN).
    """

    # Cost drift (recent vs baseline median total cost).
    cost_warn_pct: float = 0.50
    cost_critical_pct: float = 1.00

    # Latency drift (recent vs baseline p95).
    latency_info_pct: float = 0.15
    latency_warn_pct: float = 0.50
    latency_critical_pct: float = 2.00

    # Behavioral drift (tool-usage / model-distribution / prompt-length).
    behavioral_warn_pct: float = 0.40
    behavioral_runs_majority_pct: float = 0.60

    # Minimum-sample fire gates.
    min_cost_runs: int = 3
    min_behavioral_runs: int = 10
    bootstrap_min_runs: int = 30


DEFAULT_THRESHOLDS = DriftThresholds()


# --------------------------------------------------------------------------- #
# Telemetry row + baseline window (the store <-> detector data contract)       #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class JobTelemetry:
    """One immutable telemetry row: how a single agent behaved on a single job.

    Produced by :mod:`.telemetry` at job completion, accumulated per-agent, and
    read back as the rows of a :class:`BaselineWindow`. The current job's row is
    also the ``current`` argument to the detectors in :mod:`.drift`.

    Parameters
    ----------
    agent_id:
        Stable worker id (matches the reputation store's worker key).
    job_id:
        The job this row is for.
    task:
        Task/specialty tag used as the per-task baseline filter. ``None`` means
        untagged (only eligible for GLOBAL-mode comparison).
    started_at_ms:
        Wall-clock start in epoch milliseconds — the window-ordering key.
        (Wall, not monotonic: baselines window by calendar age, like AgentScope's
        ``started_at_ms``.)
    model:
        The model the agent *actually* ran. The model-substitution signal keys
        off this vs the agent's baseline / declared model.
    est_cost_usd:
        Estimated cost in USD from the pricing table, or ``None`` if any LLM
        call used a missing-price model (cost-blind row — excluded from the cost
        baseline so it can't skew the median).
    latency_ms:
        End-to-end wall latency of the agent's work on this job.
    llm_call_count:
        Number of LLM calls (denominator for avg prompt length + model %).
    total_input_tokens:
        Input tokens summed across LLM calls (numerator for avg prompt length).
    tool_call_counts:
        Per-tool call count (behavioral signal 1). Often sparse/empty.
    model_call_counts:
        Per-model LLM call count (behavioral signal 2). Usually
        ``{model: llm_call_count}`` for single-model agents.
    """

    agent_id: str
    job_id: str
    task: str | None
    started_at_ms: int
    model: str
    est_cost_usd: float | None
    latency_ms: int
    llm_call_count: int = 0
    total_input_tokens: int = 0
    tool_call_counts: dict[str, int] = field(default_factory=dict)
    model_call_counts: dict[str, int] = field(default_factory=dict)

    @property
    def avg_prompt_tokens(self) -> float | None:
        """Average input tokens per LLM call, or ``None`` if no LLM calls."""
        if self.llm_call_count <= 0:
            return None
        return self.total_input_tokens / self.llm_call_count


@dataclass(frozen=True, slots=True)
class BaselineWindow:
    """An agent's prior telemetry, the population a current row is judged against.

    Built by :mod:`.telemetry` from the agent's stored rows (optionally filtered
    to one task for PER_TASK mode, and to a recency window). The detectors in
    :mod:`.drift` read the aggregates off this object; they never touch the
    store directly.

    ``cost_samples`` excludes cost-blind rows (``est_cost_usd is None``) so the
    cost median is computed only over priced rows; ``per_task_count`` /
    ``global_count`` are the *row* counts used for tier + fire-gate decisions.
    """

    samples: tuple[JobTelemetry, ...]
    mode: BaselineMode
    tier: SampleSizeTier
    task_filter: str | None
    window_days: int
    global_count: int
    per_task_count: int

    @property
    def n(self) -> int:
        """Number of rows in this window (post task/recency filtering)."""
        return len(self.samples)

    @property
    def cost_samples(self) -> tuple[float, ...]:
        """Priced costs only (cost-blind rows dropped), for the cost baseline."""
        return tuple(
            s.est_cost_usd for s in self.samples if s.est_cost_usd is not None
        )

    @property
    def models_seen(self) -> frozenset[str]:
        """The distinct models the agent has run in this window."""
        return frozenset(s.model for s in self.samples)

    @property
    def label(self) -> str:
        """Buyer-facing sample-size label, e.g. ``(n=12 task)`` / ``(n=40 global)``."""
        if self.tier is SampleSizeTier.NO_BASELINE:
            return "(no baseline)"
        if self.mode is BaselineMode.GLOBAL:
            return f"(n={self.global_count} global)"
        suffix = (
            ", bootstrap"
            if self.tier is SampleSizeTier.PER_TASK_BOOTSTRAP
            else ""
        )
        return f"(n={self.per_task_count} task{suffix})"


# --------------------------------------------------------------------------- #
# Drift-result types (ported from drift.rs, + the new ModelSubstitution)       #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class CostDrift:
    """Cost moved vs baseline median. ``delta_pct`` is fractional (+0.5 = +50%)."""

    current_usd: float
    baseline_median_usd: float
    delta_pct: float
    severity: Severity


@dataclass(frozen=True, slots=True)
class LatencyDrift:
    """Latency moved vs baseline p95. ``delta_pct`` is fractional."""

    current_ms: int
    baseline_p95_ms: int
    delta_pct: float
    severity: Severity


@dataclass(frozen=True, slots=True)
class ToolUsageShift:
    """One tool whose per-job call count shifted beyond ``behavioral_warn_pct``."""

    tool: str
    current_count: int
    baseline_mean_count: float
    delta_pct: float


@dataclass(frozen=True, slots=True)
class ModelShiftRow:
    """One model whose share of LLM calls shifted vs baseline distribution."""

    model: str
    current_share: float
    baseline_share: float
    delta_pct: float


@dataclass(frozen=True, slots=True)
class PromptLengthShift:
    """Average prompt length (input tokens / LLM call) moved vs baseline mean."""

    current_avg_tokens: float
    baseline_avg_tokens: float
    delta_pct: float


@dataclass(frozen=True, slots=True)
class BehavioralDrift:
    """Aggregate behavioral drift block. Empty sub-lists are suppressed upstream."""

    task_label: str
    tool_usage_shifts: tuple[ToolUsageShift, ...] = ()
    model_shifts: tuple[ModelShiftRow, ...] = ()
    prompt_length: PromptLengthShift | None = None
    sample_size_annotation_n: int | None = None


@dataclass(frozen=True, slots=True)
class ModelSubstitution:
    """NEW signal — the "frontier price, open-weight model" tell.

    Fires when the agent's current model diverges from how it has historically
    behaved *and/or* from what its bid price implies. Two independent triggers,
    either of which sets ``flagged``:

    * ``model_switch`` — the current model was never seen in the agent's
      baseline window (it quietly swapped models).
    * ``price_mismatch`` — the bid price implies a frontier-tier model but the
      estimated cost of the model actually run implies a far cheaper tier
      (``implied_overcharge_ratio`` = bid-implied cost / actual est cost).

    ``severity`` is CRITICAL when both trigger, WARN when one does, else INFO.
    """

    current_model: str
    baseline_models: tuple[str, ...]
    model_switch: bool
    price_mismatch: bool
    implied_overcharge_ratio: float | None
    severity: Severity

    @property
    def flagged(self) -> bool:
        return self.model_switch or self.price_mismatch


@dataclass(frozen=True, slots=True)
class DriftReport:
    """Top-level result of one drift evaluation of a current row vs its baseline.

    ``flagged`` is the single boolean reputation/UI consumes: True when any
    sub-signal reached WARN or worse. ``overall_severity`` is the max across all
    present sub-signals (INFO when nothing fired). ``baseline_label`` carries the
    sample-size caveat for buyer-facing display.
    """

    agent_id: str
    job_id: str
    baseline_label: str
    overall_severity: Severity
    flagged: bool
    cost: CostDrift | None = None
    latency: LatencyDrift | None = None
    behavioral: BehavioralDrift | None = None
    model_substitution: ModelSubstitution | None = None
    # Set when there was no usable baseline; report is informational only.
    suppressed_reason: str | None = None


__all__ = [
    "BaselineMode",
    "SampleSizeTier",
    "Severity",
    "DriftThresholds",
    "DEFAULT_THRESHOLDS",
    "JobTelemetry",
    "BaselineWindow",
    "CostDrift",
    "LatencyDrift",
    "ToolUsageShift",
    "ModelShiftRow",
    "PromptLengthShift",
    "BehavioralDrift",
    "ModelSubstitution",
    "DriftReport",
]
