"""Verifier tests — all offline (MockBackend returns crafted JSON). No network.

Covers parsing (happy / fenced / garbage / malformed / count-mismatch, all fail-safe),
the verdict→settlement mapping, the seeded-liar catch (the project's core proof,
proven WITHOUT a live model), calibration (reliability/ECE/threshold), and that a
ClaimVerdict feeds the /metrics ClaimRecord (vocab in sync).
"""

from __future__ import annotations

import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from agent_exchange.core import MockBackend
from agent_exchange.metrics import ClaimRecord
from agent_exchange.verify import (
    LENIENT,
    ClaimVerdict,
    Verdict,
    Verifier,
    ece,
    pairs_from,
    pick_threshold,
    reliability_curve,
    rule_settlement,
)
from agent_exchange.verify.verifier import _parse_verdicts

CONTRACT = "7.1 Vendor's aggregate liability shall not exceed the fees paid in the prior 12 months."
CLAIMS = ["clause 7 caps liability at the prior 12 months' fees", "clause 12 waives all indemnity"]


def _verify(reply: str, claims=CLAIMS) -> list[ClaimVerdict]:
    return asyncio.run(Verifier(MockBackend(reply=reply)).verify(CONTRACT, claims))


# ── parsing ──

def test_happy_path():
    reply = json.dumps([
        {"verdict": "confirmed", "confidence": 0.95, "reason": "matches 7.1", "evidence_quote": "7.1 Vendor's aggregate liability shall not exceed the fees paid in the prior 12 months."},
        {"verdict": "unsupported", "confidence": 0.9, "reason": "no clause 12 in the contract", "evidence_quote": None},
    ])
    vs = _verify(reply)
    assert [v.verdict for v in vs] == [Verdict.CONFIRMED, Verdict.UNSUPPORTED]
    assert vs[0].confidence == 0.95 and vs[0].evidence_quote
    assert vs[1].evidence_quote is None  # unsupported ⇒ no evidence


def test_fenced_json_parses():
    reply = "```json\n" + json.dumps([{"verdict": "partial", "confidence": 0.7, "reason": "narrower", "evidence_quote": "7.1"}, {"verdict": "unsupported", "confidence": 0.8, "reason": "absent"}]) + "\n```"
    vs = _verify(reply)
    assert vs[0].verdict is Verdict.PARTIAL and vs[1].verdict is Verdict.UNSUPPORTED


def test_garbage_fails_safe_never_pays():
    vs = _verify("the model rambled and produced no JSON at all")
    assert all(v.verdict is Verdict.UNSUPPORTED and v.confidence == 0.0 for v in vs)
    assert all(v.needs_human() for v in vs)  # fail-safe ⇒ escalate, never auto-pay


def test_count_mismatch_and_malformed_entry_fail_safe_per_claim():
    # only one entry for two claims + a bad confidence on it
    reply = json.dumps([{"verdict": "confirmed", "confidence": "high", "reason": "x"}])
    vs = _verify(reply)
    assert len(vs) == 2
    assert vs[0].verdict is Verdict.UNSUPPORTED and vs[0].confidence == 0.0  # bad confidence → fail-safe
    assert vs[1].verdict is Verdict.UNSUPPORTED and vs[1].confidence == 0.0  # missing entry → fail-safe


def test_confidence_clamped_and_validated():
    vs = _parse_verdicts(json.dumps([{"verdict": "confirmed", "confidence": 1.7, "reason": "x", "evidence_quote": "7.1"}]), ["c"])
    assert vs[0].confidence == 1.0  # clamped
    try:
        ClaimVerdict("c", Verdict.CONFIRMED, 2.0, "r")
        raise AssertionError("confidence>1 must raise")
    except ValueError:
        pass


# ── the seeded-liar catch: the core proof, offline ──

def test_seeded_liar_caught_and_not_paid():
    """A fabricated claim → verifier returns UNSUPPORTED → it earns $0 of the payout."""
    reply = json.dumps([
        {"verdict": "confirmed", "confidence": 0.95, "reason": "matches 7.1", "evidence_quote": "7.1 Vendor's aggregate liability..."},
        {"verdict": "unsupported", "confidence": 0.92, "reason": "clause 12 fabricated — absent from contract", "evidence_quote": None},
    ])
    vs = _verify(reply)
    ruling = rule_settlement(vs, threshold=0.6)
    assert ruling.n_unsupported == 1               # the lie was caught
    assert ruling.pay_fraction == 0.5              # only the 1 real claim earns; the fabricated one earns $0
    assert ruling.escalate is False                # both confident → no human needed
    assert ruling.all_clean is False               # a fabricated claim was present


# ── settlement mapping ──

def test_rule_settlement_policies_and_escalation():
    mk = lambda v, c: ClaimVerdict("x", v, c, "r")
    claims = [mk(Verdict.CONFIRMED, 0.9), mk(Verdict.PARTIAL, 0.9), mk(Verdict.UNSUPPORTED, 0.9)]
    # default STRICT: a partial earns $0 → only the 1 fully-confirmed claim of 3 pays
    strict = rule_settlement(claims)
    assert strict.policy == "strict"
    assert abs(strict.pay_fraction - (1.0 + 0.0 + 0.0) / 3) < 1e-9
    # LENIENT: a partial earns half — the verdict is identical, only the policy differs
    lenient = rule_settlement(claims, policy=LENIENT)
    assert abs(lenient.pay_fraction - (1.0 + 0.5 + 0.0) / 3) < 1e-9
    # verdict counts are policy-INDEPENDENT (the semantics don't move with the business rule)
    assert (strict.n_confirmed, strict.n_partial, strict.n_unsupported) == (1, 1, 1)
    assert (lenient.n_confirmed, lenient.n_partial, lenient.n_unsupported) == (1, 1, 1)
    # all-confirmed pays full under either policy
    assert rule_settlement([mk(Verdict.CONFIRMED, 0.9), mk(Verdict.CONFIRMED, 0.9)]).pay_fraction == 1.0
    # low confidence → escalate; empty → 0
    esc = rule_settlement([mk(Verdict.CONFIRMED, 0.4)], threshold=0.6)
    assert esc.escalate is True and esc.n_escalated == 1
    assert rule_settlement([]).pay_fraction == 0.0


# ── calibration ──

def test_calibration_curve_ece_threshold():
    # miscalibrated: claims at conf 0.9 but only 50% correct → ECE ≈ 0.4
    pairs = [(0.9, True), (0.9, False)]
    assert abs(ece(pairs) - 0.4) < 1e-9
    bins = reliability_curve(pairs, n_bins=10)
    assert sum(b.count for b in bins) == 2

    # threshold: high-confidence claims are correct, a 0.6 one is wrong
    pairs2 = [(0.95, True), (0.9, True), (0.85, True), (0.6, False), (0.55, False)]
    assert pick_threshold(pairs2, target_accuracy=0.9) == 0.85
    assert pick_threshold([(0.5, False)], target_accuracy=0.9) == 1.0  # never trustworthy → always escalate


def test_pairs_from_labels_and_predictions():
    labels = {"c1": "confirmed", "c2": "unsupported", "c3": "uncertain", "c4": "partial"}
    preds = {"c1": ("confirmed", 0.9), "c2": ("confirmed", 0.7), "c4": ("partial", 0.8)}  # c3 skipped, no pred for it anyway
    pairs = pairs_from(labels, preds)
    assert (0.9, True) in pairs       # c1: verifier agreed
    assert (0.7, False) in pairs      # c2: verifier wrong (said confirmed, gold unsupported)
    assert (0.8, True) in pairs       # c4: agreed on partial
    assert len(pairs) == 3            # 'uncertain' c3 excluded


# ── /metrics vocab sync ──

def test_claimverdict_feeds_metrics_record():
    cv = ClaimVerdict("clause 7 caps liability", Verdict.PARTIAL, 0.7, "narrower")
    rec = ClaimRecord(worker_id="w1", claim_text=cv.claim, verdict=cv.verdict.value, confidence=cv.confidence)
    assert rec.verdict == "partial" and rec.claim_hash  # 'partial' is a valid metrics verdict now


def _run_all():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"  ✓ {fn.__name__}")
    print(f"\n{len(fns)} passed")


if __name__ == "__main__":
    _run_all()
