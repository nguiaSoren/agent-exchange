"""Calibration harness — turns labeled verifier outcomes into a trustworthy threshold.

Calibration discipline: never claim "calibrated" without evidence. You feed it
`(predicted_confidence, was_correct)` pairs from a hand-labeled
set; it gives you:
  - a **reliability curve** (per-confidence-bucket: predicted vs empirical accuracy),
  - **ECE** (expected calibration error — how far the model's confidence is from reality),
  - **`pick_threshold`** — the lowest confidence at/above which the verifier hits a target
    accuracy, so you can auto-act above it and escalate below it.

Pure, dependency-free, deterministic. The metric story rests on this:
the headline "$0 paid for fabricated work" is only credible if the gate is calibrated,
not vibes.

ECE and the reliability diagram are standard, published calibration metrics
(Guo et al., "On Calibration of Modern Neural Networks", 2017) — implemented fresh.
"""

from __future__ import annotations

from dataclasses import dataclass

Pair = tuple[float, bool]  # (predicted_confidence in [0,1], was_correct)


@dataclass(frozen=True, slots=True)
class Bin:
    lo: float
    hi: float
    count: int
    mean_confidence: float   # mean predicted confidence in this bin
    accuracy: float          # empirical fraction correct in this bin


def reliability_curve(pairs: list[Pair], n_bins: int = 10) -> list[Bin]:
    """Bucket pairs by predicted confidence; report predicted vs empirical accuracy.
    A well-calibrated verifier has `mean_confidence ≈ accuracy` in every bin."""
    if not 1 <= n_bins <= 100:
        raise ValueError("n_bins must be in [1,100]")
    edges = [i / n_bins for i in range(n_bins + 1)]
    out: list[Bin] = []
    for b in range(n_bins):
        lo, hi = edges[b], edges[b + 1]
        # last bin is inclusive of 1.0
        members = [p for p in pairs if (lo <= p[0] < hi) or (b == n_bins - 1 and p[0] == 1.0)]
        if not members:
            out.append(Bin(lo, hi, 0, 0.0, 0.0))
            continue
        n = len(members)
        out.append(
            Bin(
                lo=lo,
                hi=hi,
                count=n,
                mean_confidence=sum(c for c, _ in members) / n,
                accuracy=sum(1 for _, ok in members if ok) / n,
            )
        )
    return out


def ece(pairs: list[Pair], n_bins: int = 10) -> float:
    """Expected Calibration Error: Σ (bin_weight · |mean_confidence − accuracy|).
    0.0 = perfectly calibrated; higher = the model's confidence lies."""
    if not pairs:
        return 0.0
    total = len(pairs)
    return sum(
        (b.count / total) * abs(b.mean_confidence - b.accuracy)
        for b in reliability_curve(pairs, n_bins)
        if b.count
    )


def pairs_from(
    labels: dict[str, str],
    predictions: dict[str, tuple[str, float]],
) -> list[Pair]:
    """Build `(confidence, was_correct)` pairs from human gold labels + verifier predictions.

    `labels`: {case_id → human verdict} (from the labeling tool's labels.json).
    `predictions`: {case_id → (verifier_verdict, verifier_confidence)} from a live run.
    A case labeled "uncertain", or with no prediction, is skipped (honest — don't
    calibrate on cases the human couldn't call)."""
    out: list[Pair] = []
    for case_id, gold in labels.items():
        if gold == "uncertain":
            continue
        pred = predictions.get(case_id)
        if pred is None:
            continue
        verdict, confidence = pred
        out.append((float(confidence), verdict == gold))
    return out


def pick_threshold(pairs: list[Pair], target_accuracy: float = 0.9) -> float:
    """Lowest confidence `t` such that claims with confidence ≥ t are correct at
    ≥ `target_accuracy`. Auto-act at/above `t`; escalate below it. Returns 1.0 if no
    threshold reaches the target (i.e. always escalate — the honest answer when the
    verifier isn't trustworthy on this set)."""
    if not pairs:
        return 1.0
    confidences = sorted({round(c, 4) for c, _ in pairs})
    for t in confidences:
        kept = [ok for c, ok in pairs if c >= t]
        if kept and (sum(kept) / len(kept)) >= target_accuracy:
            return t
    return 1.0
