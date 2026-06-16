"""Cross-source verifier — claim-vs-MANY-sources, surfacing corroboration & divergence.

The single-document verifier asks "does THIS document support the claim?". Cross-source
verification (the PARALLAX job type) asks the richer question a multi-source world needs:
*across these sources, is the claim corroborated, single-sourced, or do the sources DIVERGE?*
This is the regime where ablation became a useful corroboration signal (finding F-I): a
genuine claim grounds in ≥2 sources (survives ablation), a fabrication grounds in none.

It runs the base single-document `Verifier` against EACH source independently (one batched
call per source), then aggregates the per-source verdicts into a corroboration level:

  * CORROBORATED  — ≥2 sources confirm, none reject       (high trust)
  * SINGLE_SOURCE — exactly 1 source confirms, none reject (lower trust — only one witness)
  * DIVERGENT     — ≥1 confirms AND ≥1 rejects             (the sources DISAGREE — surface it)
  * UNCORROBORATED— 0 sources confirm                      (no support anywhere → withhold)

Honest limit: the base verdict ``UNSUPPORTED`` conflates "this source is silent on it" with
"this source contradicts it", so DIVERGENT here means "at least one source confirms and at
least one does not corroborate" — a true contradiction and a mere silence are not yet
distinguished (a dedicated contradiction check is the obvious next refinement).
"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass
from enum import Enum

from ..core.types import Message
from .schema import DEFAULT_THRESHOLD, Verdict
from .verifier import Verifier


class Corroboration(str, Enum):
    CORROBORATED = "corroborated"
    SINGLE_SOURCE = "single_source"
    DIVERGENT = "divergent"
    UNCORROBORATED = "uncorroborated"


@dataclass(frozen=True, slots=True)
class SourceVerdict:
    label: str
    verdict: str          # confirmed | partial | unsupported
    confidence: float
    confirms: bool        # CONFIRMED and conf ≥ threshold


@dataclass(frozen=True, slots=True)
class CrossSourceVerdict:
    claim: str
    per_source: tuple     # tuple[SourceVerdict]
    n_confirming: int
    n_rejecting: int      # sources that returned UNSUPPORTED (silent-or-contradict)
    level: Corroboration
    corroboration_score: float   # n_confirming / n_sources — a confidence-by-witnesses signal

    @property
    def trustworthy(self) -> bool:
        """Auto-trust only a corroborated claim (≥2 agreeing witnesses, no dissent)."""
        return self.level is Corroboration.CORROBORATED


@dataclass
class CrossSourceVerifier:
    """Runs the base `Verifier` per source and aggregates corroboration across sources."""

    base: Verifier
    threshold: float = DEFAULT_THRESHOLD

    async def verify_claims(
        self, claims: list[str], sources: list[tuple[str, str]]
    ) -> list[CrossSourceVerdict]:
        """Verify each claim against every source; aggregate per claim.

        ``sources`` = list of (label, document_text). One batched base-verify call per source
        (all claims), run concurrently, then transposed to per-claim cross-source verdicts.
        """
        if not claims or not sources:
            return []
        # per_source_verdicts[s][i] = source s's verdict on claim i
        per_source_verdicts = await asyncio.gather(
            *[self.base.verify(text, claims) for _label, text in sources]
        )
        out: list[CrossSourceVerdict] = []
        for i, claim in enumerate(claims):
            svs: list[SourceVerdict] = []
            for (label, _text), verdicts in zip(sources, per_source_verdicts):
                v = verdicts[i] if i < len(verdicts) else None
                if v is None:
                    svs.append(SourceVerdict(label, "unsupported", 0.0, False))
                    continue
                confirms = v.verdict is Verdict.CONFIRMED and v.confidence >= self.threshold and not v.needs_human(self.threshold)
                svs.append(SourceVerdict(label, v.verdict.value, v.confidence, confirms))
            out.append(self._aggregate(claim, svs, len(sources)))
        return out

    def _aggregate(self, claim: str, svs: list[SourceVerdict], n_sources: int) -> CrossSourceVerdict:
        n_conf = sum(s.confirms for s in svs)
        n_rej = sum(s.verdict == "unsupported" for s in svs)
        return _level(claim, svs, n_conf, n_rej, n_sources)


def _level(claim, svs, n_conf, n_rej, n_sources) -> CrossSourceVerdict:
    if n_conf >= 2 and n_rej == 0:
        level = Corroboration.CORROBORATED
    elif n_conf == 1 and n_rej == 0:
        level = Corroboration.SINGLE_SOURCE
    elif n_conf >= 1 and n_rej >= 1:
        level = Corroboration.DIVERGENT
    else:
        level = Corroboration.UNCORROBORATED
    return CrossSourceVerdict(
        claim=claim, per_source=tuple(svs), n_confirming=n_conf, n_rejecting=n_rej,
        level=level, corroboration_score=(n_conf / n_sources if n_sources else 0.0),
    )


# --------------------------------------------------------------------------- #
# Stance-based cross-source verifier — distinguishes CONTRADICT from SILENT.   #
# --------------------------------------------------------------------------- #
# The confirm/reject path above conflates "this source contradicts the claim" with "this
# source is silent on it" (both are base-verdict UNSUPPORTED), so a partial-coverage source
# (e.g. an amendment that only lists CHANGES) wrongly reads as dissent and a corroborated
# claim looks DIVERGENT. The stance path asks each source a 3-way question — support /
# contradict / silent — so silence no longer counts as dissent.

_STANCE_SYS = (
    "You assess ONE source's stance on each claim. For each claim decide, using ONLY this "
    "source's text: 'support' (the source states or clearly implies the claim is true), "
    "'contradict' (the source states something INCOMPATIBLE with the claim — e.g. a different "
    "number/period for the same term), or 'silent' (the source simply does not address the "
    "claim's subject). Silence is NOT contradiction. Output ONLY a JSON array, one object per "
    'claim IN ORDER: {"stance": "support|contradict|silent", "confidence": 0..1}.'
)


def _parse_stances(text: str, n: int) -> list[tuple[str, float]]:
    m = re.search(r"\[.*\]", text or "", re.DOTALL)
    if not m:
        return [("silent", 0.0)] * n
    try:
        arr = json.loads(m.group(0))
    except (json.JSONDecodeError, ValueError):
        return [("silent", 0.0)] * n
    out: list[tuple[str, float]] = []
    for i in range(n):
        if i < len(arr) and isinstance(arr[i], dict):
            st = str(arr[i].get("stance", "silent")).strip().lower()
            if st not in ("support", "contradict", "silent"):
                st = "silent"
            try:
                conf = float(arr[i].get("confidence", 0.0))
            except (TypeError, ValueError):
                conf = 0.0
            out.append((st, conf))
        else:
            out.append(("silent", 0.0))
    return out


@dataclass
class StanceCrossSourceVerifier:
    """Cross-source verifier that asks each source a 3-way stance (support/contradict/silent).

    Fixes the silent-vs-contradict conflation: a source silent on a claim no longer counts as
    dissent, so a corroborated claim (true, but only covered by some sources) is no longer
    mis-flagged DIVERGENT. One stance call per source (all claims), run concurrently.
    """

    backend: object  # ModelBackend
    threshold: float = DEFAULT_THRESHOLD

    async def verify_claims(self, claims: list[str], sources: list[tuple[str, str]]) -> list[CrossSourceVerdict]:
        if not claims or not sources:
            return []
        per_source = await asyncio.gather(*[self._stances(text, claims) for _l, text in sources])
        out: list[CrossSourceVerdict] = []
        for i, claim in enumerate(claims):
            svs: list[SourceVerdict] = []
            n_support = n_contra = 0
            for (label, _text), stances in zip(sources, per_source):
                st, conf = stances[i] if i < len(stances) else ("silent", 0.0)
                supports = st == "support" and conf >= self.threshold
                contradicts = st == "contradict" and conf >= self.threshold
                n_support += supports
                n_contra += contradicts
                svs.append(SourceVerdict(label, st, conf, confirms=supports))
            out.append(_level(claim, svs, n_support, n_contra, len(sources)))
        return out

    async def _stances(self, source_text: str, claims: list[str]) -> list[tuple[str, float]]:
        numbered = "\n".join(f"{i+1}. {c}" for i, c in enumerate(claims))
        user = f'SOURCE:\n"""\n{source_text.strip()}\n"""\n\nCLAIMS:\n{numbered}\n\nReturn the JSON array now.'
        res = await self.backend.complete([Message.system(_STANCE_SYS), Message.user(user)], temperature=0.0, max_tokens=1500)
        return _parse_stances(res.text, len(claims))


# --------------------------------------------------------------------------- #
# Refined 5-way stance verifier — confidence-weighted corroboration.          #
# --------------------------------------------------------------------------- #
# The 3-way stance (support/contradict/silent) fixed the silence-vs-contradiction
# conflation on EASY cases, but it still loses on the HARD ones: a source that only
# ENTAILS the claim (implied-not-stated) or only backs PART of it (partial-coverage)
# is forced into 'support' or 'silent', flattening a half-witness into a full one or
# into nothing. The refined path asks a 5-WAY stance and aggregates with a CONFIDENCE
# WEIGHT, so an entailed claim can still corroborate (if confident) and a partial
# source counts as only half a witness.

_REFINED_STANCE_SYS = (
    "You assess ONE source's stance on each claim, using ONLY this source's text. For each "
    "claim choose EXACTLY one of FIVE stances:\n"
    "  - 'support': the source explicitly STATES the claim (asserts it directly).\n"
    "  - 'implied': the source does NOT state the claim, but its content clearly ENTAILS it "
    "(a confident reader concludes the claim must be true from what is written).\n"
    "  - 'partially_supports': the source backs PART of the claim but not all of it (e.g. the "
    "claim conjoins two facts and only one appears, or a range/qualifier is only partly met).\n"
    "  - 'contradict': the source states something INCOMPATIBLE with the claim — including a "
    "DIFFERENT number/period/amount for the SAME term, even if worded differently.\n"
    "  - 'silent': the source simply does not address the claim's subject. Silence is NOT "
    "contradiction.\n"
    "Output ONLY a JSON array, one object per claim IN ORDER: "
    '{"stance": "support|implied|partially_supports|contradict|silent", "confidence": 0..1}.'
)

_REFINED_STANCES = ("support", "implied", "partially_supports", "contradict", "silent")


def _parse_refined_stances(text: str, n: int) -> list[tuple[str, float]]:
    """Parse the 5-way stance JSON array, fail-soft to ('silent', 0.0) per slot."""
    m = re.search(r"\[.*\]", text or "", re.DOTALL)
    if not m:
        return [("silent", 0.0)] * n
    try:
        arr = json.loads(m.group(0))
    except (json.JSONDecodeError, ValueError):
        return [("silent", 0.0)] * n
    out: list[tuple[str, float]] = []
    for i in range(n):
        if i < len(arr) and isinstance(arr[i], dict):
            st = str(arr[i].get("stance", "silent")).strip().lower()
            if st not in _REFINED_STANCES:
                st = "silent"
            try:
                conf = float(arr[i].get("confidence", 0.0))
            except (TypeError, ValueError):
                conf = 0.0
            out.append((st, max(0.0, min(1.0, conf))))
        else:
            out.append(("silent", 0.0))
    return out


@dataclass(frozen=True, slots=True)
class RefinedSourceVerdict:
    """A 5-way per-source verdict carrying the witness WEIGHT it contributes."""

    label: str
    stance: str           # support | implied | partially_supports | contradict | silent
    confidence: float
    witness_weight: float  # signed contribution to corroboration (see aggregation rules)


def _aggregate_refined(
    claim: str,
    rsvs: list[RefinedSourceVerdict],
    n_sources: int,
    *,
    threshold: float,
    implied_conf: float,
    full_witness: float,
    half_witness: float,
) -> CrossSourceVerdict:
    """Confidence-weighted 5-way aggregation → a `Corroboration` level.

    Witness weights (per source), gated by confidence ``threshold`` unless noted:
      * support               → +``full_witness`` (1.0)            — a full witness.
      * implied, conf ≥ ``implied_conf`` (a STRICTER bar, default 0.7)
                              → +``full_witness`` (1.0)            — confident entailment is a full witness.
      * implied, conf < bar   → +``half_witness`` (0.5)            — weak entailment is only half a witness.
      * partially_supports    → +``half_witness`` (0.5)            — a half witness (backs only part of the claim).
      * contradict            → counts as DISSENT (one rejector).
      * silent                → 0 (ignored — silence is neither support nor dissent).

    Level thresholds are confidence-AWARE — they sum WEIGHTS, not raw counts:
      * any dissent (≥1 contradict) AND ≥1 positive witness   → DIVERGENT (the sources disagree).
      * dissent only, no positive witness                     → UNCORROBORATED.
      * witness_sum ≥ ~2 full witnesses (≥ 2·full − ε)        → CORROBORATED.
      * 0 < witness_sum < 2 full witnesses                    → SINGLE_SOURCE (one full, or two halves — a lone/weak witness).
      * witness_sum == 0                                      → UNCORROBORATED.

    Two ``partially_supports`` sources (0.5+0.5=1.0) therefore land at SINGLE_SOURCE, not
    CORROBORATED — half-witnesses do not add up to the trust of two independent full witnesses.
    """
    witness_sum = 0.0
    n_dissent = 0
    for rsv in rsvs:
        if rsv.stance == "contradict" and rsv.confidence >= threshold:
            n_dissent += 1
        else:
            witness_sum += max(0.0, rsv.witness_weight)
    eps = 1e-6
    has_witness = witness_sum > eps
    if n_dissent >= 1 and has_witness:
        level = Corroboration.DIVERGENT
    elif n_dissent >= 1:
        level = Corroboration.UNCORROBORATED
    elif witness_sum >= 2 * full_witness - eps:
        level = Corroboration.CORROBORATED
    elif has_witness:
        level = Corroboration.SINGLE_SOURCE
    else:
        level = Corroboration.UNCORROBORATED
    # Map the refined verdicts onto the existing SourceVerdict tuple for API compatibility
    # (downstream readers expect `per_source` of SourceVerdicts). `confirms` = it added witness.
    svs = tuple(
        SourceVerdict(r.label, r.stance, r.confidence, confirms=(r.witness_weight > eps and r.stance != "contradict"))
        for r in rsvs
    )
    # n_confirming counts full-strength witnesses; n_rejecting counts confident contradictions.
    n_conf = sum(1 for r in rsvs if r.witness_weight >= full_witness - eps and r.stance != "contradict")
    return CrossSourceVerdict(
        claim=claim, per_source=svs, n_confirming=n_conf, n_rejecting=n_dissent,
        level=level, corroboration_score=(witness_sum / n_sources if n_sources else 0.0),
    )


@dataclass
class RefinedStanceCrossSourceVerifier:
    """Cross-source verifier with a 5-WAY stance + CONFIDENCE-WEIGHTED corroboration.

    Asks each source: support / implied / partially_supports / contradict / silent (one call
    per source, all claims, run concurrently), then aggregates witness WEIGHTS (not raw
    counts) into a `Corroboration` level. See ``_aggregate_refined`` for the exact, defensible
    rules. The motivation is the HARD cases the 3-way taxonomy collapses:

      * IMPLIED-NOT-STATED — a source that entails the claim is now an 'implied' (a full
        witness when confident), not a forced 'support' or 'silent'.
      * PARTIAL-COVERAGE   — a source backing only part of the claim is 'partially_supports'
        (a HALF witness), not an over-counted full 'support'.
      * PARAPHRASE-/NUMERIC-CONTRADICTION — the prompt explicitly flags a different number for
        the same term as 'contradict'.

    Kept SEPARATE from `StanceCrossSourceVerifier` (which is unchanged) so existing callers are
    untouched; this is the strictly-richer variant.
    """

    backend: object  # ModelBackend
    threshold: float = DEFAULT_THRESHOLD
    implied_conf: float = 0.7   # stricter bar: only confident entailment is a FULL witness
    full_witness: float = 1.0
    half_witness: float = 0.5

    async def verify_claims(self, claims: list[str], sources: list[tuple[str, str]]) -> list[CrossSourceVerdict]:
        if not claims or not sources:
            return []
        per_source = await asyncio.gather(*[self._stances(text, claims) for _l, text in sources])
        out: list[CrossSourceVerdict] = []
        for i, claim in enumerate(claims):
            rsvs: list[RefinedSourceVerdict] = []
            for (label, _text), stances in zip(sources, per_source):
                st, conf = stances[i] if i < len(stances) else ("silent", 0.0)
                rsvs.append(self._weigh(label, st, conf))
            out.append(_aggregate_refined(
                claim, rsvs, len(sources), threshold=self.threshold,
                implied_conf=self.implied_conf, full_witness=self.full_witness,
                half_witness=self.half_witness,
            ))
        return out

    def _weigh(self, label: str, stance: str, conf: float) -> RefinedSourceVerdict:
        """Map a (stance, confidence) to a signed witness weight per the aggregation rules."""
        weight = 0.0
        if stance == "support" and conf >= self.threshold:
            weight = self.full_witness
        elif stance == "implied" and conf >= self.threshold:
            weight = self.full_witness if conf >= self.implied_conf else self.half_witness
        elif stance == "partially_supports" and conf >= self.threshold:
            weight = self.half_witness
        # contradict → weight stays 0 here; dissent is handled in _aggregate_refined.
        # silent / sub-threshold → 0.
        return RefinedSourceVerdict(label, stance, conf, witness_weight=weight)

    async def _stances(self, source_text: str, claims: list[str]) -> list[tuple[str, float]]:
        numbered = "\n".join(f"{i+1}. {c}" for i, c in enumerate(claims))
        user = f'SOURCE:\n"""\n{source_text.strip()}\n"""\n\nCLAIMS:\n{numbered}\n\nReturn the JSON array now.'
        res = await self.backend.complete([Message.system(_REFINED_STANCE_SYS), Message.user(user)], temperature=0.0, max_tokens=1500)
        return _parse_refined_stances(res.text, len(claims))
