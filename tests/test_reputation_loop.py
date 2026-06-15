"""Reputation-loop tests — the hire→work→verify→reputation cycle, proven OFFLINE.

The loop closes the market: after the verifier grades a deliverable, each worker's
VERIFIED outcome is folded back into its reputation, so the next Thompson-sampled
hiring round reflects who actually delivered (not who merely bid well). These tests
pin the four claims that make the loop both correct and FAIR:

  1. **Quality-based outcomes** (`worker_outcomes`) — a worker is graded on ITS OWN
     findings: clean (no `unsupported`, ≥1 finding) ⇒ success; pay_fraction is the
     lenient verified fraction `(n_confirmed + 0.5·n_partial) / n_findings`.
  2. **THE FAIRNESS TEST** — a clean worker and a fabricator share ONE deliverable.
     The no-fabrication payment gate withholds the WHOLE job (money is collective),
     but reputation lands only on the offender: the clean worker's track record rises
     while the liar's falls.
  3. **THE LOOP CLOSES** — run several jobs; the consistently-clean worker's
     reputation climbs well above the fabricator's, and a Thompson draw seeded over
     many rngs prefers it on average. Reputation now DRIVES the hire.
  4. **CONTEXTUAL bandit** — a worker strong in TAX but weak/absent in IP draws a
     higher per-specialty Thompson value for `specialty="tax"` than `"ip"`.
  5. **Receipt evidence** — when a signed receipt + a ledger are supplied, each update
     is anchored as a `"reputation_update"` ledger entry carrying the receipt's
     signer/signature, and the chain still verifies.

Run:  PYTHONHASHSEED=1 .venv/bin/python tests/test_reputation_loop.py
      (also collected by pytest as plain sync test_* functions)
"""

from __future__ import annotations

import os
import random
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from agent_exchange.audit.report import AuditedFinding
from agent_exchange.audit.room_audit_types import RoomAuditResult
from agent_exchange.market.hiring_types import Hire
from agent_exchange.market.reputation import JsonReputationStore
from agent_exchange.market.reputation_loop import apply_outcomes, worker_outcomes
from agent_exchange.market.selection import thompson_value
from agent_exchange.payments.audit_types import Receipt, SignedReceipt, WorkerReceiptLine
from agent_exchange.payments.ledger import HashChainedLedger
from agent_exchange.payments.receipts import make_receipt_signer
from agent_exchange.verify.schema import ClaimVerdict, Verdict
from agent_exchange.workers.finding import Finding


# ── builders ──────────────────────────────────────────────────────────────────


def _build_deliverable(triples: list[tuple[str, str, Verdict]]) -> RoomAuditResult:
    """A `RoomAuditResult` from ``(worker, claim, verdict)`` triples.

    Each triple becomes an `AuditedFinding(Finding(worker, ...), ClaimVerdict(...))`
    with confidence 1.0 (so nothing ever escalates) set as the result's `.audited`.
    The reporter side is left empty — `worker_outcomes` grades only specialist work.
    """
    audited: list[AuditedFinding] = []
    for i, (worker, claim, verdict) in enumerate(triples):
        audited.append(
            AuditedFinding(
                finding=Finding(worker=worker, clause_ref=str(i), claim=claim, severity="medium"),
                verdict=ClaimVerdict(claim=claim, verdict=verdict, confidence=1.0, reason=""),
            )
        )
    return RoomAuditResult(
        work_room_id="room-test",
        audited=tuple(audited),
        report_summary="",
        report_audited=(),
    )


def _hire(worker: str) -> Hire:
    """A minimal `Hire` for ``worker`` (price/value irrelevant to the reputation fold)."""
    return Hire(worker=worker, price_atomic=1, value=1.0, relevance=1.0)


# A fixed 32-byte hex key so receipt signing is deterministic in tests.
_TEST_KEY = "0x" + "11" * 32


def _signed_receipt(deliverable_hash: str = "0x" + "ab" * 32) -> SignedReceipt:
    """A genuinely-signed `SignedReceipt` over a minimal hand-made receipt."""
    signer = make_receipt_signer(_TEST_KEY)
    receipt = Receipt(
        job_id="job-1",
        deliverable_hash=deliverable_hash,
        gate_passed=True,
        pay_fraction=1.0,
        timestamp="T0000",
        workers=(
            WorkerReceiptLine(
                worker="clean",
                verdict_summary="1 confirmed, 0 partial, 0 unsupported",
                authorized_atomic=1,
                settled_atomic=1,
                tx_hash="0xtx",
                status="settled",
            ),
        ),
    )
    return signer.sign(receipt)


# ── 1. quality-based worker_outcomes ────────────────────────────────────────────


def test_worker_outcomes_quality_grading():
    """Per-worker, quality-based: success + lenient pay_fraction on a worker's OWN findings."""
    deliverable = _build_deliverable(
        [
            # two confirmed → clean success, full credit
            ("two_conf", "c0", Verdict.CONFIRMED),
            ("two_conf", "c1", Verdict.CONFIRMED),
            # one confirmed + one partial → success, (1 + 0.5)/2 == 0.75
            ("conf_partial", "c0", Verdict.CONFIRMED),
            ("conf_partial", "c1", Verdict.PARTIAL),
            # one unsupported → NOT a success (fabricated)
            ("liar", "c0", Verdict.UNSUPPORTED),
        ]
    )
    # "silent" delivered nothing — hired but produced no findings.
    hires = [_hire(w) for w in ("two_conf", "conf_partial", "liar", "silent")]
    by_worker = {o.worker: o for o in worker_outcomes(deliverable, hires)}

    # 2 confirmed → success, pay_fraction 1.0
    assert by_worker["two_conf"].success is True
    assert abs(by_worker["two_conf"].pay_fraction - 1.0) < 1e-9

    # 1 confirmed + 1 partial → success, pay_fraction 0.75
    assert by_worker["conf_partial"].success is True
    assert abs(by_worker["conf_partial"].pay_fraction - 0.75) < 1e-9

    # 1 unsupported → NOT a success
    assert by_worker["liar"].success is False

    # 0 findings → not a success, pay_fraction 0.0
    assert by_worker["silent"].success is False
    assert by_worker["silent"].pay_fraction == 0.0
    assert by_worker["silent"].n_findings == 0


# ── 2. THE FAIRNESS TEST (the headline) ─────────────────────────────────────────


def test_fairness_clean_rises_liar_falls_in_a_poisoned_job():
    """A clean worker and a fabricator share ONE deliverable. The no-fab gate would
    withhold the WHOLE job (money is collective) — but reputation lands only on the
    offender: `clean` rises, `liar` falls, globally AND per-specialty."""
    with tempfile.TemporaryDirectory() as d:
        store = JsonReputationStore(os.path.join(d, "rep.json"))
        deliverable = _build_deliverable(
            [
                ("clean", "vendor liability is capped at 12 months' fees", Verdict.CONFIRMED),
                ("liar", "the contract grants a unilateral 90-day termination", Verdict.UNSUPPORTED),
            ]
        )
        hires = [_hire("clean"), _hire("liar")]

        updated = apply_outcomes(store, deliverable, hires)

        clean = store.get("clean")
        liar = store.get("liar")

        # The clean worker's reputation went UP (above the 0.5 prior); the liar's fell.
        assert clean.success_rate > 0.5
        assert liar.success_rate < 0.5
        # The headline assertion: clean now out-ranks the liar on reputation.
        assert clean.success_rate > liar.success_rate

        # The returned records match what the store now holds.
        assert abs(updated["clean"].success_rate - clean.success_rate) < 1e-12
        assert abs(updated["liar"].success_rate - liar.success_rate) < 1e-12

        # Per-specialty (worker name == its specialty) moved the same direction.
        assert "clean" in clean.per_specialty
        assert "liar" in liar.per_specialty
        assert clean.per_specialty["clean"]["success_rate"] > 0.5
        assert liar.per_specialty["liar"]["success_rate"] < 0.5
        assert (
            clean.per_specialty["clean"]["success_rate"]
            > liar.per_specialty["liar"]["success_rate"]
        )


# ── 3. THE LOOP CLOSES — reputation drives the hire ─────────────────────────────


def test_loop_closes_reputation_drives_the_hire():
    """Start two fresh workers at the 0.5 prior. Run several jobs where `good` always
    delivers clean and `bad` always fabricates. `good`'s success_rate rises well above
    `bad`'s, and a Thompson draw (seeded over many rngs, specialty=worker) prefers
    `good` on average — the reputation now DRIVES the hire."""
    with tempfile.TemporaryDirectory() as d:
        store = JsonReputationStore(os.path.join(d, "rep.json"))

        # Both start neutral.
        assert store.get("good").success_rate == 0.5
        assert store.get("bad").success_rate == 0.5

        for _ in range(6):
            deliverable = _build_deliverable(
                [
                    ("good", "a confirmed, well-grounded finding", Verdict.CONFIRMED),
                    ("bad", "a fabricated, unsupported finding", Verdict.UNSUPPORTED),
                ]
            )
            apply_outcomes(store, deliverable, [_hire("good"), _hire("bad")])

        good = store.get("good")
        bad = store.get("bad")
        # The track records have clearly separated.
        assert good.success_rate > 0.8
        assert bad.success_rate < 0.2
        assert good.success_rate - bad.success_rate > 0.5

        # Thompson now prefers `good`: average the per-specialty draw over many seeds.
        n_seeds = 400
        good_total = 0.0
        bad_total = 0.0
        good_wins = 0
        for seed in range(n_seeds):
            g = thompson_value(good, relevance=1.0, rng=random.Random(seed), specialty="good")
            b = thompson_value(bad, relevance=1.0, rng=random.Random(seed), specialty="bad")
            good_total += g
            bad_total += b
            if g > b:
                good_wins += 1
        # On average the reputation-driven draw favours the clean worker decisively.
        assert good_total / n_seeds > bad_total / n_seeds
        assert good_wins > n_seeds * 0.75


# ── 4. CONTEXTUAL bandit — per-specialty draw ───────────────────────────────────


def test_contextual_bandit_specialty_routing():
    """A worker with a strong TAX track record but weak/absent IP record draws a higher
    Thompson value for specialty='tax' than specialty='ip' over many seeds."""
    with tempfile.TemporaryDirectory() as d:
        store = JsonReputationStore(os.path.join(d, "rep.json"))

        # Build a strong TAX record: several clean tax jobs.
        for _ in range(6):
            deliverable = _build_deliverable([("expert", "a clean tax finding", Verdict.CONFIRMED)])
            # tag the fold to the "tax" specialty (worker name == specialty in apply_outcomes,
            # so drive the store directly here to isolate the specialty under test)
            store.update("expert", success=True, pay_fraction=1.0, specialty="tax")

        # Build a WEAK IP record: a couple of fabricated ip jobs.
        for _ in range(2):
            store.update("expert", success=False, pay_fraction=0.0, specialty="ip")

        rec = store.get("expert")
        assert rec.per_specialty["tax"]["success_rate"] > rec.per_specialty["ip"]["success_rate"]

        n_seeds = 400
        tax_total = 0.0
        ip_total = 0.0
        tax_wins = 0
        for seed in range(n_seeds):
            t = thompson_value(rec, relevance=1.0, rng=random.Random(seed), specialty="tax")
            p = thompson_value(rec, relevance=1.0, rng=random.Random(seed), specialty="ip")
            tax_total += t
            ip_total += p
            if t > p:
                tax_wins += 1
        # The contextual draw routes this worker to TAX, not IP.
        assert tax_total / n_seeds > ip_total / n_seeds
        assert tax_wins > n_seeds * 0.6


# ── 5. Receipt evidence anchoring ───────────────────────────────────────────────


def test_reputation_update_anchored_to_signed_receipt_in_ledger():
    """With a signed receipt + a ledger, each update is appended as a 'reputation_update'
    entry carrying the receipt's signer/signature, and the chain still verifies."""
    with tempfile.TemporaryDirectory() as d:
        store = JsonReputationStore(os.path.join(d, "rep.json"))
        ledger = HashChainedLedger(os.path.join(d, "ledger.jsonl"))
        signed = _signed_receipt()

        deliverable = _build_deliverable(
            [
                ("clean", "a confirmed finding", Verdict.CONFIRMED),
                ("liar", "a fabricated finding", Verdict.UNSUPPORTED),
            ]
        )
        hires = [_hire("clean"), _hire("liar")]

        apply_outcomes(store, deliverable, hires, receipt=signed, ledger=ledger, timestamp="T0000")

        rep_entries = [e for e in ledger.entries() if e.event == "reputation_update"]
        # One ledger entry per worker.
        assert len(rep_entries) == 2
        workers_logged = {e.payload["worker"] for e in rep_entries}
        assert workers_logged == {"clean", "liar"}

        for e in rep_entries:
            ev = e.payload["evidence"]
            # The entry carries the receipt's signer + signature + deliverable hash.
            assert ev["signer"] == signed.signer_address
            assert ev["signature"] == signed.signature
            assert ev["deliverable_hash"] == signed.receipt.deliverable_hash

        # The hash chain is intact end-to-end.
        assert ledger.verify_chain() is True


def test_no_ledger_entries_without_a_receipt():
    """A ledger but NO receipt writes nothing (anchoring needs both)."""
    with tempfile.TemporaryDirectory() as d:
        store = JsonReputationStore(os.path.join(d, "rep.json"))
        ledger = HashChainedLedger(os.path.join(d, "ledger.jsonl"))
        deliverable = _build_deliverable([("clean", "a confirmed finding", Verdict.CONFIRMED)])

        apply_outcomes(store, deliverable, [_hire("clean")], ledger=ledger)  # no receipt

        assert ledger.entries() == []


# ── 6. Behavioral drift — the SECOND, INDEPENDENT cheat-signal ───────────────────


def test_drift_flag_overrides_success_even_when_content_is_clean():
    """A worker with ALL-confirmed findings but flagged by the drift detector fails the
    behavioral check: success=False, drifted=True, while pay_fraction stays the full
    content fraction (drift is a reputation signal, not a content one). Folding it into
    a store drops its success_rate BELOW the same worker's run without the drift flag."""
    deliverable = _build_deliverable(
        [
            ("worker", "a confirmed finding", Verdict.CONFIRMED),
            ("worker", "another confirmed finding", Verdict.CONFIRMED),
        ]
    )
    hires = [_hire("worker")]

    drifted = {o.worker: o for o in worker_outcomes(deliverable, hires, drift_flags={"worker": True})}["worker"]
    clean = {o.worker: o for o in worker_outcomes(deliverable, hires)}["worker"]

    # Content was clean (all confirmed) in BOTH — only the behavioral check differs.
    assert drifted.success is False
    assert drifted.drifted is True
    assert abs(drifted.pay_fraction - 1.0) < 1e-9  # content credit unchanged
    assert clean.success is True
    assert clean.drifted is False
    assert abs(clean.pay_fraction - 1.0) < 1e-9

    # Folding into a store: the drift-flagged run lands a LOWER success_rate.
    with tempfile.TemporaryDirectory() as d:
        s_drift = JsonReputationStore(os.path.join(d, "drift.json"))
        s_clean = JsonReputationStore(os.path.join(d, "clean.json"))
        apply_outcomes(s_drift, deliverable, hires, drift_flags={"worker": True})
        apply_outcomes(s_clean, deliverable, hires)
        assert s_drift.get("worker").success_rate < s_clean.get("worker").success_rate


def test_drift_flags_none_reproduces_today_exactly():
    """drift_flags=None (or omitted) is byte-for-byte the content-only behavior: known
    outcomes are unchanged and every outcome reports drifted=False."""
    deliverable = _build_deliverable(
        [
            ("two_conf", "c0", Verdict.CONFIRMED),
            ("two_conf", "c1", Verdict.CONFIRMED),
            ("liar", "c0", Verdict.UNSUPPORTED),
        ]
    )
    hires = [_hire("two_conf"), _hire("liar"), _hire("silent")]

    explicit_none = {o.worker: o for o in worker_outcomes(deliverable, hires, drift_flags=None)}
    omitted = {o.worker: o for o in worker_outcomes(deliverable, hires)}

    # The two call forms agree exactly.
    assert explicit_none.keys() == omitted.keys()
    for w in explicit_none:
        assert explicit_none[w] == omitted[w]

    # Known content outcomes unchanged, and nothing is marked drifted.
    assert omitted["two_conf"].success is True
    assert abs(omitted["two_conf"].pay_fraction - 1.0) < 1e-9
    assert omitted["liar"].success is False
    assert omitted["silent"].success is False and omitted["silent"].n_findings == 0
    assert all(not o.drifted for o in omitted.values())


def test_drift_plus_unsupported_no_double_jeopardy():
    """A worker that BOTH fabricated (unsupported) AND drifted stays success=False —
    no weirdness from two independent gates both firing. drifted is recorded True."""
    deliverable = _build_deliverable([("worker", "a fabricated finding", Verdict.UNSUPPORTED)])
    hires = [_hire("worker")]
    out = {o.worker: o for o in worker_outcomes(deliverable, hires, drift_flags={"worker": True})}["worker"]
    assert out.success is False
    assert out.drifted is True
    assert out.n_unsupported == 1


def test_drift_flag_recorded_in_ledger_entry():
    """With a signed receipt + ledger + drift_flags, the anchored 'reputation_update'
    entry carries drifted=True for the flagged worker (and False for the unflagged)."""
    with tempfile.TemporaryDirectory() as d:
        store = JsonReputationStore(os.path.join(d, "rep.json"))
        ledger = HashChainedLedger(os.path.join(d, "ledger.jsonl"))
        signed = _signed_receipt()

        deliverable = _build_deliverable(
            [
                ("drifter", "a confirmed finding", Verdict.CONFIRMED),
                ("steady", "a confirmed finding", Verdict.CONFIRMED),
            ]
        )
        hires = [_hire("drifter"), _hire("steady")]

        apply_outcomes(
            store,
            deliverable,
            hires,
            receipt=signed,
            drift_flags={"drifter": True},
            ledger=ledger,
            timestamp="T0000",
        )

        by_worker = {
            e.payload["worker"]: e.payload
            for e in ledger.entries()
            if e.event == "reputation_update"
        }
        assert by_worker["drifter"]["drifted"] is True
        assert by_worker["drifter"]["success"] is False
        assert by_worker["steady"]["drifted"] is False
        assert by_worker["steady"]["success"] is True
        assert ledger.verify_chain() is True


def test_non_drifted_worker_unaffected_when_a_peer_drifts():
    """In a job where ONE worker drifts, a clean non-drifted peer is untouched:
    success=True, drifted=False, full content credit."""
    deliverable = _build_deliverable(
        [
            ("drifter", "a confirmed finding", Verdict.CONFIRMED),
            ("clean", "a confirmed finding", Verdict.CONFIRMED),
        ]
    )
    hires = [_hire("drifter"), _hire("clean")]
    out = {o.worker: o for o in worker_outcomes(deliverable, hires, drift_flags={"drifter": True})}

    assert out["drifter"].success is False and out["drifter"].drifted is True
    assert out["clean"].success is True and out["clean"].drifted is False
    assert abs(out["clean"].pay_fraction - 1.0) < 1e-9


def _run_all():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"  ✓ {fn.__name__}")
    print(f"\n{len(fns)} passed")


if __name__ == "__main__":
    _run_all()
