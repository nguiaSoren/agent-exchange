"""The verifier. Grades each worker claim against the contract text.

Built on the provider-agnostic backend: it takes any `ModelBackend` (a strong
frontier model live, a `MockBackend` in tests). `verify()` returns one
`ClaimVerdict` per claim, in order, with a calibrated confidence and (for
confirmed/partial) the verbatim supporting span.

Robust parsing: LLMs wrap JSON in prose/fences and occasionally
emit garbage. We extract the JSON array defensively; if a claim can't be parsed, it
FAILS SAFE → `unsupported`, confidence `0.0`, `needs_human=True`. The invariant that
matters for an economy: an unverifiable result NEVER auto-pays. You withhold and
escalate, never silently confirm.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, replace

from ..core import Message, ModelBackend
from .graders import (
    GateRoute,
    extracted_claims,
    route_claim,
    substring_overlap_ratio,
    token_jaccard_distinctive,
)
from .prompts import build_user_message, verifier_system
from .schema import DEFAULT_THRESHOLD, ClaimVerdict, Verdict

_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.IGNORECASE)
_VALID = {"confirmed", "partial", "unsupported"}

# A model-cited evidence_quote whose substring-overlap against the document is BELOW
# this is treated as an unambiguous FABRICATION: the overwhelming majority of the
# quote's distinctive 10-char windows are absent from the document, i.e. the span was
# not actually quoted from it (only incidental short-phrase collisions remain). A
# genuinely verbatim quote scores 1.0 — far above this floor — so the gate can only ADD
# catches and can NEVER flip a real, present-in-document quote to fabricated.
_FABRICATION_OVERLAP_FLOOR = 0.25
# Between the fabrication floor and this ceiling a quote is only PARTIALLY present
# (some windows match, some are invented): we LOWER confidence proportionally to the
# overlap (never raise it). A quote fully present in the document has overlap 1.0 and
# is left untouched.
_WEAK_OVERLAP_CEILING = 0.6

# Multiplicative confidence penalty the ABLATION GATE applies when a confirmed/partial
# verdict cites a quote that is ABSENT from the document even after normalization. This
# only ever LOWERS confidence (and pairs with force_needs_human so the claim escalates);
# it never flips the verdict or zeroes the payment on the deterministic signal alone —
# the LLM-judge's verdict and the calibrated threshold remain the arbiter, so this can
# never manufacture a false-withhold of a genuinely-grounded claim.
_ABSENT_QUOTE_CONFIDENCE_PENALTY = 0.5


class VerifierParseError(Exception):
    """Raised internally when the model output can't be parsed into verdicts."""


def _strip_fences(text: str) -> str:
    return _FENCE_RE.sub("", text.strip())


def _extract_array(text: str) -> str:
    """Pull the first top-level JSON array out of a possibly-noisy completion."""
    t = _strip_fences(text)
    start = t.find("[")
    end = t.rfind("]")
    if start == -1 or end == -1 or end < start:
        raise VerifierParseError("no JSON array found in verifier output")
    return t[start : end + 1]


def _coerce_verdict(raw: object) -> Verdict:
    s = str(raw).strip().lower()
    if s not in _VALID:
        # tolerate a near-miss ("confirm"/"supported"/etc.) but be conservative
        if s.startswith("confirm"):
            return Verdict.CONFIRMED
        if s.startswith("partial"):
            return Verdict.PARTIAL
        raise VerifierParseError(f"unrecognized verdict {raw!r}")
    return Verdict(s)


def _coerce_confidence(raw: object) -> float:
    try:
        c = float(raw)
    except (TypeError, ValueError):
        raise VerifierParseError(f"confidence not a number: {raw!r}")
    return max(0.0, min(1.0, c))  # clamp into [0,1]


def _fail_safe(claim: str, why: str) -> ClaimVerdict:
    """Unparseable/unverifiable ⇒ withhold + escalate (never auto-pay on doubt)."""
    return ClaimVerdict(
        claim=claim,
        verdict=Verdict.UNSUPPORTED,
        confidence=0.0,
        reason=f"verifier output unusable ({why}); failing safe → withhold + human review",
        evidence_quote=None,
    )


def _parse_verdicts(text: str, claims: list[str]) -> list[ClaimVerdict]:
    """Parse the model output into one ClaimVerdict per claim, in order.

    Per-claim fail-safe: a malformed entry becomes a withhold+escalate verdict
    rather than aborting the whole job. A wholesale parse failure fails every claim
    safe (still never auto-pays)."""
    try:
        items = json.loads(_extract_array(text))
        if not isinstance(items, list):
            raise VerifierParseError("top-level JSON is not an array")
    except (json.JSONDecodeError, VerifierParseError) as e:
        return [_fail_safe(c, str(e)) for c in claims]

    out: list[ClaimVerdict] = []
    for i, claim in enumerate(claims):
        if i >= len(items) or not isinstance(items[i], dict):
            out.append(_fail_safe(claim, "missing/!object entry"))
            continue
        obj = items[i]
        try:
            verdict = _coerce_verdict(obj.get("verdict"))
            confidence = _coerce_confidence(obj.get("confidence"))
            reason = str(obj.get("reason", "")).strip() or "(no reason given)"
            quote = obj.get("evidence_quote")
            quote = str(quote) if quote not in (None, "", "null") else None
            if verdict is Verdict.UNSUPPORTED:
                quote = None  # no evidence for an unsupported claim
            out.append(ClaimVerdict(claim, verdict, confidence, reason, quote))
        except (VerifierParseError, ValueError) as e:
            out.append(_fail_safe(claim, str(e)))
    return out


def _grade_one(verdict: ClaimVerdict, document: str, *, gate: bool) -> ClaimVerdict:
    """Attach deterministic audit signals to one verdict, and (if ``gate``) enforce them.

    ALWAYS (gate on or off): compute the model-free signals and surface them on the
    verdict — ``deterministic_overlap`` / ``deterministic_jaccard`` (the model-cited
    ``evidence_quote`` vs the ``document``) and ``atoms_graded`` (atomic facts in the
    claim). These are read-only audit fields; computing them changes no verdict.

    WHEN ``gate`` is enabled, two STRICTLY-STRENGTHENING actions apply to a
    confirmed/partial verdict that carries an ``evidence_quote``:

      1. **Short-circuit (the killer check).** If the cited quote does NOT appear in
         the document (overlap ≈ 0), that is an unambiguous fabrication — the verdict
         is flipped to ``unsupported`` at confidence 0.0 WITHOUT a second model call.
         This can only ADD catches; it never flips a real (present-in-document) quote.

      2. **Confidence penalty.** For a quote that is only WEAKLY corroborated
         (``0 < overlap < _WEAK_OVERLAP_CEILING``) the confidence is scaled DOWN by the
         overlap fraction. Confidence is only ever lowered, never raised.

    An ``unsupported`` verdict (or one without a quote) is never up-graded here — the
    gate only ever withholds harder, preserving the fail-safe invariant.
    """
    atoms = len(extracted_claims(verdict.claim))
    quote = verdict.evidence_quote
    if not quote:
        # No model-cited span (e.g. unsupported): nothing to ground, just annotate.
        return replace(verdict, atoms_graded=atoms)

    overlap = substring_overlap_ratio(quote, document)
    jaccard = token_jaccard_distinctive(quote, document)

    annotated = replace(
        verdict,
        deterministic_overlap=overlap,
        deterministic_jaccard=jaccard,
        atoms_graded=atoms,
    )
    if not gate or verdict.verdict is Verdict.UNSUPPORTED:
        return annotated

    # 1. Killer check: cited quote not actually in the document → fabrication.
    if overlap < _FABRICATION_OVERLAP_FLOOR:
        return replace(
            annotated,
            verdict=Verdict.UNSUPPORTED,
            confidence=0.0,
            reason=(
                "deterministic gate: cited evidence_quote does not appear in the "
                "document (overlap≈0) — fabricated span → withhold"
            ),
            evidence_quote=None,
            deterministic_short_circuit=True,
        )

    # 2. Weak-but-present corroboration → lower confidence proportionally.
    if overlap < _WEAK_OVERLAP_CEILING:
        return replace(annotated, confidence=annotated.confidence * overlap)

    return annotated


def _ablation_route_one(verdict: ClaimVerdict, document: str) -> ClaimVerdict:
    """Run the ABLATION GATE on one verdict and apply only the SAFE actions.

    HARD INVARIANT: this layer NEVER auto-withholds and never sets ``unsupported`` /
    $0 on the deterministic signal alone. It is *necessary-not-sufficient* grounding —
    the LLM-judge's verdict + the calibrated pay/escalate threshold stay the arbiter.
    It only:

      * annotates the route + signals (``deterministic_route``, ``ablation_survived``,
        ``verbatim_overlap``, ``normalized``, ``jaccard``) for audit;
      * on route ``ESCALATE`` (cited quote absent post-normalize): LOWERS confidence by
        a fixed penalty AND sets ``force_needs_human=True`` (escalate to a human),
        while STILL leaving the model's verdict in place for the judge;
      * on route ``JUDGE`` (present but fails ablation — single-sourced span, could be a
        genuine quote or a copy-a-real-span fabrication): FLAGS it (route annotation),
        no penalty, no withhold — it goes to the judge;
      * on route ``SUPPORTED`` (present + survives ablation): nothing but annotation.

    An ``unsupported`` verdict (the model already withheld) is annotated but never
    escalated harder here — the gate strengthens grounding, it does not relax a
    withhold. Confidence is only ever lowered, never raised.
    """
    sig = route_claim(verdict.claim, verdict.evidence_quote, document)
    annotated = replace(
        verdict,
        deterministic_verbatim_overlap=sig.verbatim_overlap,
        deterministic_jaccard=(
            sig.jaccard if verdict.deterministic_jaccard is None else verdict.deterministic_jaccard
        ),
        deterministic_ablation_survived=sig.ablation_survived,
        deterministic_route=sig.route.value,
        deterministic_normalized=sig.normalized,
    )

    # The model already withheld → leave it withheld (gate never relaxes a withhold).
    if verdict.verdict is Verdict.UNSUPPORTED:
        return annotated

    if sig.route is GateRoute.ESCALATE:
        # Cited quote is absent even after normalization. PENALIZE + ESCALATE, but do
        # NOT flip the verdict or zero it — the judge + threshold decide.
        return replace(
            annotated,
            confidence=annotated.confidence * _ABSENT_QUOTE_CONFIDENCE_PENALTY,
            force_needs_human=True,
            escalate_reason=(
                "ablation gate: cited evidence_quote is not verbatim-present in the "
                "document (even after normalization) — penalized + escalated to a human; "
                "verdict left to the judge (no auto-withhold)"
            ),
        )

    # SUPPORTED or JUDGE → annotate only; both still reach / are confirmed by the judge.
    return annotated


@dataclass
class Verifier:
    """Grades claims against a contract using `backend`."""

    backend: ModelBackend
    threshold: float = DEFAULT_THRESHOLD
    max_tokens: int = 4000  # generous: gpt-5/o-series spend reasoning tokens against this budget
    # Document-type word for the prompts (default reproduces the contract verifier).
    document_label: str = field(default="contract", kw_only=True)
    # Deterministic claim-vs-evidence gate (graders.py). OFF by default so existing
    # behavior + locked catch-rate numbers are byte-identical. When ON, the gate
    # short-circuits any confirmed/partial verdict whose model-cited evidence_quote is
    # NOT a substring of the document (overlap≈0 ⇒ fabrication → unsupported), and
    # lowers confidence for weakly-corroborated quotes — strictly strengthening
    # catch-rate, never flipping a genuinely-grounded claim to fabricated.
    #
    # DEPRECATED: this is the original HARD short-circuit. The ablation gate below is the
    # successor. Kept available + OFF for back-compat.
    deterministic_gate: bool = field(default=False, kw_only=True)
    # The ABLATION GATE (Soren's design): a deterministic claim-vs-evidence gate IN FRONT
    # of the judge that only PENALIZES / ESCALATES / ROUTES — it NEVER auto-withholds, so
    # it cannot create a false-withhold. OFF by default so the locked offline tests
    # (test_verifier / test_catch_rate), whose MockBackends emit placeholder quotes, stay
    # byte-identical. Turn ON in production where the judge is asked to cite a verbatim
    # span (see prompts.py) so genuine quotes clear the verbatim-present floor.
    ablation_gate: bool = field(default=False, kw_only=True)

    async def verify(self, contract_text: str, claims: list[str]) -> list[ClaimVerdict]:
        if not claims:
            return []
        messages = [
            Message.system(verifier_system(self.document_label)),
            Message.user(
                build_user_message(contract_text, claims, document=self.document_label)
            ),
        ]
        result = await self.backend.complete(messages, temperature=0.0, max_tokens=self.max_tokens)
        verdicts = _parse_verdicts(result.text, claims)
        # Deterministic post-pass: always annotate audit signals; enforce the legacy
        # short-circuit only when enabled. Fail-safe verdicts (unsupported/0.0) are left
        # to withhold.
        graded = [
            _grade_one(v, contract_text, gate=self.deterministic_gate) for v in verdicts
        ]
        # The ablation gate sits IN FRONT conceptually but is applied here as a SAFE
        # post-pass: it only annotates routes + (on an absent quote) penalizes/escalates,
        # never auto-withholds. OFF by default to keep the locked numbers byte-identical.
        if self.ablation_gate:
            graded = [_ablation_route_one(v, contract_text) for v in graded]
        return graded
