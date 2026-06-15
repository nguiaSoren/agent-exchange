"""CATCH-RATE harness — measure the verifier on a KNOWN-labeled set.

The seeded-liar protocol: we hold a set of claims whose ground truth we already
know — some `GENUINE` (grounded in the contract), some `FABRICATED` (a plausible-but-
false clause an adversarial worker invented). We run the *real* verifier over them and
compare its verdicts to the labels. Because the truth is known, we can report an honest
confusion matrix instead of a vibe.

Positive class = FABRICATED ("should be withheld"). The verifier's withhold signal is a
`Verdict.UNSUPPORTED` verdict. From that, the headline numbers fall out:

  * **catch-rate** = recall on fabrications = tp / (tp + fn) — of the fabricated claims,
    the fraction the verifier caught (marked unsupported). "We catch fabrication N% of
    the time."
  * **false-withhold rate** = false-positive rate = fp / (fp + tn) — of the GENUINE
    claims, the fraction the verifier wrongly withheld (punishing real work).
  * **precision** = tp / (tp + fp) — of everything it withheld, the fraction that was
    truly fabricated.
  * **ECE** + a reliability curve over the verifier's confidence (Guo et al. 2017) —
    so "calibrated" is a measured claim, not an assertion.

Confusion matrix (positive class = fabricated):

    tp = FABRICATED & verdict UNSUPPORTED      (caught the liar)
    fn = FABRICATED & verdict NOT unsupported  (missed the liar — paid for a lie)
    fp = GENUINE    & verdict UNSUPPORTED      (false withhold — punished good work)
    tn = GENUINE    & verdict NOT unsupported  (correctly let real work through)

The run is bounded by an `asyncio.Semaphore` so a large labeled set can't cascade-429
the underlying provider. A contract-group whose verify call raises is contained, not
fatal: its claims are treated as `UNSUPPORTED` (fail-safe → withhold + human review) and
the error is logged, so one bad group never aborts the whole evaluation.
"""

from __future__ import annotations

import asyncio
import logging

from ..verify.calibration import ece, pick_threshold, reliability_curve
from ..verify.schema import ClaimVerdict, Verdict
from ..verify.verifier import Verifier
from .types import FABRICATED, GENUINE, CatchRateReport, LabeledClaim

__all__ = ["run_catch_rate", "format_report"]

_log = logging.getLogger(__name__)


def _fail_safe_verdict(claim: str, why: str) -> ClaimVerdict:
    """A claim we couldn't get a real verdict for ⇒ withhold + escalate.

    Mirrors the verifier's own fail-safe invariant: on doubt you withhold and send to a
    human, never auto-confirm. Confidence 0.0 keeps it below any sane threshold.
    """
    return ClaimVerdict(
        claim=claim,
        verdict=Verdict.UNSUPPORTED,
        confidence=0.0,
        reason=f"verify call failed ({why}); failing safe → withhold + human review",
        evidence_quote=None,
    )


async def _verify_group(
    contract: str,
    group: list[LabeledClaim],
    verifier: Verifier,
    sem: asyncio.Semaphore,
) -> list[ClaimVerdict]:
    """Verify one contract's claims under the concurrency gate, containing any failure.

    Returns one `ClaimVerdict` per claim in `group`, positionally aligned. On any raise
    (network error, parse blow-up, anything) every claim in the group fails safe to an
    `UNSUPPORTED` verdict and the error is logged at WARNING — the run never aborts.
    """
    claims = [c.claim for c in group]
    async with sem:
        try:
            verdicts = await verifier.verify(contract, claims)
        except Exception as exc:  # noqa: BLE001 — intentional: contain + log, never abort the run.
            _log.warning(
                "verify failed for a contract group (%d claims); treating as unsupported: %s",
                len(claims),
                exc,
                exc_info=True,
            )
            return [_fail_safe_verdict(c, f"{type(exc).__name__}: {exc}") for c in claims]

    # Defensive alignment: the verifier contract is one verdict per claim, in order, but
    # if a misbehaving backend ever returns the wrong count, pad/truncate fail-safe so
    # claim↔verdict alignment (and thus the labels) can never silently skew.
    if len(verdicts) != len(claims):
        _log.warning(
            "verifier returned %d verdicts for %d claims; realigning fail-safe",
            len(verdicts),
            len(claims),
        )
        fixed: list[ClaimVerdict] = []
        for i, claim in enumerate(claims):
            if i < len(verdicts):
                fixed.append(verdicts[i])
            else:
                fixed.append(_fail_safe_verdict(claim, "missing verdict from backend"))
        verdicts = fixed
    return verdicts


def _group_by_contract(cases: list[LabeledClaim]) -> list[tuple[str, list[LabeledClaim]]]:
    """Group cases by contract, preserving first-seen order (deterministic output)."""
    groups: dict[str, list[LabeledClaim]] = {}
    for case in cases:
        groups.setdefault(case.contract, []).append(case)
    return list(groups.items())


async def run_catch_rate(
    cases: list[LabeledClaim],
    verifier: Verifier,
    *,
    max_concurrency: int = 6,
    target_accuracy: float = 0.9,
    n_bins: int = 10,
) -> CatchRateReport:
    """Run the real verifier on a labeled set and compute the honest confusion matrix.

    Cases are grouped by `contract` (the verifier grades one contract + its claims at a
    time). Groups run concurrently, bounded by `asyncio.Semaphore(max_concurrency)` so a
    large set can't cascade-429 the provider. A group whose verify call raises is
    contained: its claims fail safe to `UNSUPPORTED` (logged), never aborting the run.
    Claim↔verdict alignment is preserved throughout, so every verdict is scored against
    the right ground-truth label.

    Scoring (positive class = FABRICATED, withhold signal = `Verdict.UNSUPPORTED`):

        tp = FABRICATED & unsupported      (caught)
        fn = FABRICATED & not-unsupported  (missed)
        fp = GENUINE    & unsupported      (false withhold)
        tn = GENUINE    & not-unsupported  (let through)

    Calibration pairs are `(verdict.confidence, was_correct)`, where `was_correct` means
    the verdict agreed with ground truth: a FABRICATED claim is correct when withheld
    (unsupported); a GENUINE claim is correct when NOT withheld (confirmed or partial).
    From those pairs we compute `ece`, `pick_threshold(target_accuracy)`, and the
    `reliability_curve` (stored as a tuple of plain dicts for the figure / JSON).

    Args:
        cases: The labeled claims to evaluate. May be empty (⇒ an all-zero report).
        verifier: The real verifier to run.
        max_concurrency: Upper bound on concurrent contract-group verify calls (>= 1).
        target_accuracy: Target accuracy for `pick_threshold` (auto-act at/above the
            returned threshold, escalate below it).
        n_bins: Number of confidence bins for ECE and the reliability curve.

    Returns:
        A `CatchRateReport` with the confusion matrix, catch-rate, false-withhold rate,
        precision, ECE, the picked threshold, and the reliability bins.

    Raises:
        ValueError: If `max_concurrency < 1`.
    """
    if max_concurrency < 1:
        raise ValueError(f"max_concurrency must be >= 1, got {max_concurrency!r}")

    n_total = len(cases)
    if not cases:
        return CatchRateReport(
            n_total=0,
            n_fabricated=0,
            n_genuine=0,
            tp=0,
            fp=0,
            tn=0,
            fn=0,
            catch_rate=0.0,
            false_withhold_rate=0.0,
            precision=0.0,
            ece=0.0,
            threshold=1.0,
            reliability=(),
        )

    groups = _group_by_contract(cases)
    sem = asyncio.Semaphore(max_concurrency)

    # Run all groups concurrently; results stay positionally aligned with `groups`.
    group_verdicts = await asyncio.gather(
        *(_verify_group(contract, group, verifier, sem) for contract, group in groups)
    )

    tp = fp = tn = fn = 0
    pairs: list[tuple[float, bool]] = []

    for (_contract, group), verdicts in zip(groups, group_verdicts):
        for case, verdict in zip(group, verdicts):
            withheld = verdict.verdict is Verdict.UNSUPPORTED
            if case.label == FABRICATED:
                if withheld:
                    tp += 1
                else:
                    fn += 1
                was_correct = withheld
            else:  # GENUINE (and any non-FABRICATED label is scored as let-through-correct)
                if withheld:
                    fp += 1
                else:
                    tn += 1
                was_correct = not withheld
            pairs.append((verdict.confidence, was_correct))

    n_fabricated = tp + fn
    n_genuine = fp + tn

    catch_rate = tp / (tp + fn) if (tp + fn) else 0.0
    false_withhold_rate = fp / (fp + tn) if (fp + tn) else 0.0
    precision = tp / (tp + fp) if (tp + fp) else 0.0

    ece_value = ece(pairs, n_bins)
    threshold = pick_threshold(pairs, target_accuracy)
    bins = reliability_curve(pairs, n_bins)
    reliability = tuple(
        {
            "lo": b.lo,
            "hi": b.hi,
            "count": b.count,
            "mean_confidence": b.mean_confidence,
            "accuracy": b.accuracy,
        }
        for b in bins
    )

    return CatchRateReport(
        n_total=n_total,
        n_fabricated=n_fabricated,
        n_genuine=n_genuine,
        tp=tp,
        fp=fp,
        tn=tn,
        fn=fn,
        catch_rate=catch_rate,
        false_withhold_rate=false_withhold_rate,
        precision=precision,
        ece=ece_value,
        threshold=threshold,
        reliability=reliability,
    )


def format_report(r: CatchRateReport) -> str:
    """Render a `CatchRateReport` as a readable multi-line summary for a run script.

    Leads with the headline catch-rate / false-withhold rate, then the confusion matrix
    (positive class = fabricated), then precision, ECE, and the picked threshold.
    """
    lines = [
        "CATCH-RATE REPORT",
        "=" * 40,
        f"  cases:        {r.n_total}  ({r.n_fabricated} fabricated, {r.n_genuine} genuine)",
        "",
        f"  catch-rate:        {r.catch_rate:6.1%}   (fabrications caught — recall)",
        f"  false-withhold:    {r.false_withhold_rate:6.1%}   (genuine wrongly withheld — FPR)",
        f"  precision:         {r.precision:6.1%}   (of withholds, fraction truly fabricated)",
        "",
        "  confusion matrix (positive = fabricated, withhold = unsupported):",
        f"    tp (caught)          = {r.tp}",
        f"    fn (missed liar)     = {r.fn}",
        f"    fp (false withhold)  = {r.fp}",
        f"    tn (let through)     = {r.tn}",
        "",
        f"  ECE:               {r.ece:6.4f}   (0 = perfectly calibrated)",
        f"  threshold:         {r.threshold:6.4f}   (auto-act >= this, escalate below)",
        f"  reliability bins:  {len(r.reliability)}",
        "=" * 40,
    ]
    return "\n".join(lines)
