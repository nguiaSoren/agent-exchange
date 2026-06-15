"""Verifier verdicts + the verdict→payment ruling.

The verifier's output vocabulary. A `ClaimVerdict` is the verifier's grounded judgment
of ONE claim against the contract text; `rule_settlement` turns a set of verdicts
into a payment decision under the chosen scheme:

    CONFIRMED   (conf ≥ t) → pay full
    PARTIAL     (conf ≥ t) → pay prorated (x402 `upto`)
    UNSUPPORTED (conf ≥ t) → withhold (this is the "$0 for fabricated work" path)
    any         (conf < t) → escalate to a human

The grading vocabulary: verdict + one-line rationale + calibrated
confidence; `confidence < threshold` ⇒ human review.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

# default confidence threshold below which a claim is escalated to a human
DEFAULT_THRESHOLD = 0.6


class Verdict(str, Enum):
    """The SEMANTIC verdict — a contract-verification (NLI-style) judgment, NOT a
    payment decision. Rubric:
      CONFIRMED   - mechanism + material details correct.
      PARTIAL     - mechanism correct, a material number/condition wrong (e.g. "12
                    months" when the text says 6) — directionally right, factually off.
      UNSUPPORTED - mechanism wrong, a direct contradiction, or an invented fact.
    """

    CONFIRMED = "confirmed"
    PARTIAL = "partial"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True, slots=True)
class SettlementPolicy:
    """Maps a semantic verdict → a payment weight in [0,1]. This is the BUSINESS layer,
    deliberately separate from the verdict (which stays a faithful NLI judgment). Swap
    the policy without touching the verifier or the labels."""

    name: str
    confirmed: float = 1.0
    partial: float = 0.5
    unsupported: float = 0.0

    def weight(self, v: Verdict) -> float:
        return {Verdict.CONFIRMED: self.confirmed, Verdict.PARTIAL: self.partial, Verdict.UNSUPPORTED: self.unsupported}[v]


# A PARTIAL (mechanism right, material detail wrong) earns half credit:
LENIENT = SettlementPolicy("lenient", partial=0.5)
# "$0 for ANY materially-wrong statement" — a PARTIAL earns nothing. This is the
# demo's headline policy (it's what makes "you only pay for verified work" literally true).
STRICT = SettlementPolicy("strict", partial=0.0)
DEFAULT_POLICY = STRICT


@dataclass(frozen=True, slots=True)
class ClaimVerdict:
    """One claim's grounded verdict. `evidence_quote` is the verbatim supporting
    span from the contract (powers the demo highlight), or None when unsupported.

    The trailing ``deterministic_*`` fields are OPTIONAL audit signals from the
    model-free grader layer (graders.py), all defaulting to ``None`` so every
    existing construction site keeps working unchanged:

      * ``deterministic_overlap`` — `substring_overlap_ratio(evidence_quote, document)`
        in ``[0,1]``: how much of the model's cited quote is actually verbatim in the
        document. ``~0`` is the unambiguous fabrication signal.
      * ``deterministic_jaccard`` — distinctive-token Jaccard of the quote vs the
        document (a softer corroboration of overlap).
      * ``deterministic_short_circuit`` — ``True`` when the deterministic gate flipped
        this verdict to ``unsupported`` (the quote was not in the document), so the
        ruling is auditable without re-running the model.
      * ``atoms_graded`` — count of atomic facts (date/number/currency/…) the grader
        extracted from the claim, surfaced for trace/debugging.

    The trailing ``ablation_*`` / ``deterministic_route`` fields are the *ablation gate*
    signals (the deterministic claim-vs-evidence gate that sits IN FRONT of the judge).
    All optional, all default-``None``/``False`` so every existing call site is
    unchanged. They are read-only audit fields — the gate only PENALIZES / ESCALATES /
    ROUTES, it NEVER auto-withholds, so none of these can create a false-withhold:

      * ``deterministic_verbatim_overlap`` — `verbatim_overlap_ratio(quote, document)`,
        the normalize-aware overlap (a real quote with trivial formatting diffs still
        scores ``1.0``).
      * ``deterministic_normalized`` — ``True`` when normalization was load-bearing for
        the quote to read as verbatim (raw overlap fell short, normalized cleared it).
      * ``deterministic_ablation_survived`` — ``True`` when, after the cited span is
        ablated from the document, the claim is STILL grounded elsewhere (confidently
        supported); ``False`` when the claim hung entirely on the one gifted span
        (ambiguous → routed to the judge).
      * ``deterministic_route`` — the gate's route string
        (``"supported"`` / ``"judge"`` / ``"escalate"``), for trace/audit.
      * ``escalate_reason`` — a one-line note when the gate set ``needs_human`` (e.g. a
        cited quote that is absent from the document even after normalization).
    """

    claim: str
    verdict: Verdict
    confidence: float
    reason: str
    evidence_quote: str | None = None
    # ── optional deterministic audit signals (default None ⇒ nothing breaks) ──
    deterministic_overlap: float | None = None
    deterministic_jaccard: float | None = None
    deterministic_short_circuit: bool = False
    atoms_graded: int | None = None
    # ── ablation-gate audit signals (default None/False ⇒ nothing breaks) ──
    deterministic_verbatim_overlap: float | None = None
    deterministic_normalized: bool = False
    deterministic_ablation_survived: bool | None = None
    deterministic_route: str | None = None
    escalate_reason: str | None = None
    # The ablation gate sets this when it ESCALATES (e.g. an absent cited quote): an
    # explicit, audit-visible "a human must look" flag that is independent of the
    # confidence threshold. It only ever ADDS escalation (never removes it), so it can
    # withhold-for-review but can NEVER cause a false PAY.
    force_needs_human: bool = False

    def __post_init__(self) -> None:
        if not (0.0 <= self.confidence <= 1.0):
            raise ValueError(f"confidence must be in [0,1], got {self.confidence}")

    def needs_human(self, threshold: float = DEFAULT_THRESHOLD) -> bool:
        # Escalate when the model is under-confident OR the gate forced a human review.
        # `force_needs_human` can only turn escalation ON, never off — fail-safe held.
        return self.confidence < threshold or self.force_needs_human


@dataclass(frozen=True, slots=True)
class SettlementRuling:
    """The verdict→payment bridge for one job's deliverable."""

    pay_fraction: float                 # 0..1 of the authorized amount
    escalate: bool                      # any claim below the confidence threshold → human
    n_confirmed: int
    n_partial: int
    n_unsupported: int
    n_escalated: int
    policy: str = DEFAULT_POLICY.name

    @property
    def all_clean(self) -> bool:
        return self.n_unsupported == 0 and not self.escalate


def rule_settlement(
    verdicts: list[ClaimVerdict],
    *,
    threshold: float = DEFAULT_THRESHOLD,
    policy: SettlementPolicy = DEFAULT_POLICY,
) -> SettlementRuling:
    """Map per-claim verdicts → a payment fraction + escalation flag, under `policy`.

    `pay_fraction` is the mean per-claim weight under the policy. With STRICT (default),
    a partial or unsupported claim earns $0 — so a job pays in full only when every
    claim is fully confirmed ("you only pay for verified work"). With LENIENT, a partial
    earns half. Any claim below `threshold` flips `escalate` (a human decides those
    before money moves). The verdict counts are policy-independent (the semantics).
    """
    if not verdicts:
        return SettlementRuling(0.0, False, 0, 0, 0, 0, policy.name)
    weight_sum = sum(policy.weight(v.verdict) for v in verdicts)
    escalated = [v for v in verdicts if v.needs_human(threshold)]
    return SettlementRuling(
        pay_fraction=weight_sum / len(verdicts),
        escalate=bool(escalated),
        n_confirmed=sum(v.verdict is Verdict.CONFIRMED for v in verdicts),
        n_partial=sum(v.verdict is Verdict.PARTIAL for v in verdicts),
        n_unsupported=sum(v.verdict is Verdict.UNSUPPORTED for v in verdicts),
        n_escalated=len(escalated),
        policy=policy.name,
    )
