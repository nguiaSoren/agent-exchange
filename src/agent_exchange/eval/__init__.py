"""Evaluation — the seeded-liar protocol: measure the verifier's honest catch-rate.

Inject known-bad fabricated claims alongside genuine ones, run the real verifier, and
report the confusion matrix (catch-rate, false-withhold rate, precision, ECE).
"""

from .catch_rate import format_report, run_catch_rate
from .seeded_liar import (
    generate_labeled_claims,
    gold_claims_from_calibration,
    load_fixture,
    save_fixture,
)
from .types import FABRICATED, GENUINE, CatchRateReport, LabeledClaim

__all__ = [
    "LabeledClaim",
    "CatchRateReport",
    "GENUINE",
    "FABRICATED",
    "generate_labeled_claims",
    "gold_claims_from_calibration",
    "save_fixture",
    "load_fixture",
    "run_catch_rate",
    "format_report",
]
