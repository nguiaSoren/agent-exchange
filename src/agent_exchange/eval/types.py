"""Locked types for the seeded-liar protocol — measuring the verifier's catch-rate.

We inject KNOWN-BAD fabricated claims (an adversarial worker inventing plausible-but-
false clauses) alongside GENUINE grounded claims, run the real verifier, and compare
its verdicts to the known labels. Because the ground truth is known, we can report the
honest confusion matrix:

  * **catch-rate** (recall on fabrications) — of the fabricated claims, the fraction the
    verifier marked `unsupported` (caught). The "we catch fabrication N% of the time" number.
  * **false-withhold rate** (false-positive rate) — of the genuine claims, the fraction the
    verifier wrongly marked `unsupported` (punishing real work).

Positive class = "fabricated / should-withhold". `unsupported` verdict = the verifier's
"reject/withhold" signal.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# label values
GENUINE = "genuine"
FABRICATED = "fabricated"


@dataclass(frozen=True, slots=True)
class LabeledClaim:
    """One claim with KNOWN ground truth: is it grounded in the contract, or invented?"""

    contract: str
    claim: str
    label: str          # GENUINE | FABRICATED
    source: str = ""    # provenance, e.g. "llm_liar" / "llm_genuine" / "gold" / "audit"


@dataclass(frozen=True, slots=True)
class CatchRateReport:
    """The verifier's honest confusion matrix on a labeled set.

    Confusion matrix with positive class = fabricated (should be withheld):
      tp = fabricated AND verdict unsupported (caught)
      fn = fabricated AND NOT unsupported (missed liar)
      fp = genuine    AND verdict unsupported (false withhold — punished good work)
      tn = genuine    AND NOT unsupported (correctly let through)
    """

    n_total: int
    n_fabricated: int
    n_genuine: int
    tp: int
    fp: int
    tn: int
    fn: int
    catch_rate: float            # tp / (tp + fn) — recall on fabrications
    false_withhold_rate: float   # fp / (fp + tn) — FPR on genuine
    precision: float             # tp / (tp + fp) — of withholds, the fraction truly fabricated
    ece: float                   # expected calibration error of the verifier's confidence
    threshold: float             # pick_threshold at the target accuracy
    reliability: tuple = field(default_factory=tuple)  # the reliability-curve bins (for the figure)
