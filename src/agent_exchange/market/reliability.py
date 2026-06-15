"""Reliability sample-size formulas — ported verbatim from AgentScope.

Provides two formulas (faithful ports of ``agentscope-mining/src/reliability.rs``)
and a ``reliability_badge`` helper that the bidding layer attaches to each bid so
buyers can see how many job runs back the reputation estimate.

Formula 1 — sample size for ±E margin at 95% confidence (Z = 1.96)
--------------------------------------------------------------------
    n = Z² · p · (1 − p) / E²

Worst-case p = 0.5, default E = 0.05 → ~385 runs needed at p = 0.5 (ceil of 384.16).

Formula 2 — sample size to detect a rare branch of prevalence p at 95% confidence
----------------------------------------------------------------------------------
    n > ln(confidence) / ln(1 − p)

With p = 0.01, confidence-failure-prob = 0.05 → ceil(298.07) = 299 runs.

Both formulas are pure ``math``-stdlib (no third-party deps).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

# ── constants (mirror the Rust consts exactly) ────────────────────────────────
_Z_SCORE_95: float = 1.96
_P_WORST_CASE: float = 0.5
_E_DEFAULT: float = 0.05
_CONF_RARE_BRANCH: float = 0.05  # failure-to-detect probability (= 1 − 95%)
_P_RARE_BRANCH: float = 0.01    # 1% rare branch prevalence


# ── formulas ──────────────────────────────────────────────────────────────────

def formula_1_n(p: float, e: float, z: float = _Z_SCORE_95) -> float:
    """Formula 1: ``n = Z² · p · (1 − p) / E²``.

    Returns the *raw* (non-ceiling) float — callers that need an integer should
    apply ``math.ceil`` themselves.  The Rust source applies ``ceil()`` at the
    call site inside ``ReliabilityReport::new``; we do the same in
    ``reliability_badge``.

    Args:
        p: Expected success probability (worst-case 0.5 maximises n).
        e: Desired margin of error (default 0.05 = ±5%).
        z: Z-score for the desired confidence level (default 1.96 = 95%).

    Returns:
        Required sample size as a float (apply ``math.ceil`` for a whole-run count).
    """
    return (z * z * p * (1.0 - p)) / (e * e)


def formula_2_n(p: float, confidence: float = _CONF_RARE_BRANCH) -> float:
    """Formula 2: ``n > ln(confidence) / ln(1 − p)``.

    ``confidence`` here is the *failure*-to-detect probability (0.05 = 95%
    detection confidence), matching the Rust convention.  Returns the raw float;
    callers apply ``math.ceil``.

    Args:
        p: Prevalence of the rare branch (default 0.01 = 1% of runs).
        confidence: Probability of *not* detecting the branch (0.05 = 95%
            confidence that we WILL detect it).

    Returns:
        Minimum runs required as a float (apply ``math.ceil`` for a whole number).
    """
    return math.log(confidence) / math.log(1.0 - p)


# ── badge dataclass ───────────────────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class ReliabilityBadge:
    """Buyer-facing confidence badge derived from a worker's job-run count.

    Attributes:
        n_jobs: Observed number of completed jobs for this worker.
        margin_required: Runs needed for ±E CI (Formula 1, ceil, worst-case p=0.5).
        margin_additional: Additional runs still needed (``max(0, required − n_jobs)``).
        rare_branch_required: Runs needed to detect a 1%-rare branch at 95% confidence
            (Formula 2, ceil).
        low_confidence: True when ``n_jobs < margin_required`` — the ±5% CI is NOT yet
            met and the reputation estimate should be treated with caution.
        label: Human-readable one-liner for display (reuses existing chip styling).
    """

    n_jobs: int
    margin_required: int
    margin_additional: int
    rare_branch_required: int
    low_confidence: bool
    label: str


def reliability_badge(n_jobs: int, *, e: float = _E_DEFAULT) -> ReliabilityBadge:
    """Compute a buyer-facing ``ReliabilityBadge`` for a worker with ``n_jobs`` completed jobs.

    The badge encodes both sample-size formulas so renderers don't recompute, and
    exposes a ``low_confidence`` flag so the UI can show a subtle warning chip when
    the worker's track record is too thin to trust the ±5% margin.

    Args:
        n_jobs: How many jobs this worker has completed (``ReputationRecord.n_jobs``).
        e: Desired margin of error for Formula 1 (default 0.05 = ±5%).

    Returns:
        A frozen ``ReliabilityBadge`` with all fields populated.

    Examples::

        >>> b = reliability_badge(47)
        >>> b.margin_required
        385
        >>> b.margin_additional
        338
        >>> b.rare_branch_required
        299
        >>> b.low_confidence
        True
        >>> reliability_badge(500).low_confidence
        False
    """
    margin_raw = formula_1_n(_P_WORST_CASE, e, _Z_SCORE_95)
    margin_required = math.ceil(margin_raw)
    margin_additional = max(0, margin_required - n_jobs)

    rare_raw = formula_2_n(_P_RARE_BRANCH, _CONF_RARE_BRANCH)
    rare_branch_required = math.ceil(rare_raw)

    low_confidence = n_jobs < margin_required

    e_pct = round(e * 100)
    if low_confidence:
        label = (
            f"{n_jobs} job{'s' if n_jobs != 1 else ''} · low confidence"
            f" (needs ~{margin_required} for ±{e_pct}%)"
        )
    else:
        label = f"{n_jobs} jobs · ±{e_pct}% confident"

    return ReliabilityBadge(
        n_jobs=n_jobs,
        margin_required=margin_required,
        margin_additional=margin_additional,
        rare_branch_required=rare_branch_required,
        low_confidence=low_confidence,
        label=label,
    )
