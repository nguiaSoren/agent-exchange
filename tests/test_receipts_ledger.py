"""Audit-trail tests — the signed receipt + the hash-chained ledger, proven OFFLINE.

The settlement gate fires lifecycle hooks; a `ReceiptLedgerRecorder` turns those into a
tamper-evident ledger, and a `SignedReceipt` binds the verified work to the payment.
These tests inject the same `_FakeGate` as `tests/test_settlement.py` (no chain, no
keys) and assert the two audit guarantees end to end:

  1. **Signed receipt** — ``build_receipt`` → ``sign`` → ``verify_receipt`` is True for an
     honest receipt; mutate the signed receipt (bump a settled amount) and verification
     is False — a tampered receipt does not verify against its signature.
  2. **Hash-chained ledger** — append a run of events → ``verify_chain()`` True; corrupt
     the on-disk file → False. The chain is tamper-EVIDENT.
  3. **Hooks → ledger** — run ``settle_job`` with a `ReceiptLedgerRecorder` on a temp
     ledger + a fixed clock and assert the ledger captured the expected events (a
     "settled" per paid worker, a "withheld"/"verify_fail" where applicable) and the
     chain still verifies.
  4. **"$0 for fabricated work" trail** — one UNSUPPORTED claim → the whole job is
     withheld → the ledger shows "withheld" entries and NO "settled" entries, and the
     finalized receipt has ``gate_passed`` False.
  5. **Backward compatibility** — ``hooks=None`` keeps ``settle_job`` behaving exactly as
     before (no crash, same `JobSettlement`).

Run:  PYTHONHASHSEED=1 .venv/bin/python tests/test_receipts_ledger.py
"""

from __future__ import annotations

import asyncio
import dataclasses
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from agent_exchange.audit.report import AuditedFinding
from agent_exchange.audit.room_audit_types import RoomAuditResult
from agent_exchange.market.hiring_types import Hire
from agent_exchange.metrics import usdc
from agent_exchange.payments.ledger import HashChainedLedger
from agent_exchange.payments.receipts import build_receipt, make_receipt_signer, verify_receipt
from agent_exchange.payments.recorder import ReceiptLedgerRecorder
from agent_exchange.payments.settlement import settle_job
from agent_exchange.verify.schema import LENIENT, ClaimVerdict, Verdict
from agent_exchange.workers.finding import Finding


# ── the injected fake gate (same shape as tests/test_settlement.py) ────────────


class _FakeGate:
    """In-memory `PaymentGate` — no chain, no keys. Records each settle + call order."""

    def __init__(self, *, verify_ok: bool = True) -> None:
        self.verify_ok = verify_ok
        self.settled: list[tuple[int, str]] = []
        self.calls: list[tuple[str, str]] = []
        self._seq = 0

    def build_requirement(self, *, amount_atomic: int, pay_to: str) -> object:
        return {"amount": amount_atomic, "pay_to": pay_to}

    async def authorize(self, requirement: object) -> object:
        return {"sig": "0xauth", "pay_to": requirement["pay_to"]}  # type: ignore[index]

    async def verify(self, payload: object, requirement: object) -> bool:
        self.calls.append(("verify", requirement["pay_to"]))  # type: ignore[index]
        return self.verify_ok

    async def settle(self, payload: object, requirement: object, *, amount_atomic: int) -> str:
        pay_to = requirement["pay_to"]  # type: ignore[index]
        self.calls.append(("settle", pay_to))
        self.settled.append((amount_atomic, pay_to))
        tx = f"0xfake{self._seq}"
        self._seq += 1
        return tx


# ── deliverable / hire builders (same shape as tests/test_settlement.py) ───────

_CONTRACT_REF = "Vendor's aggregate liability is capped at the prior 12 months' fees."


def _audited(verdict: Verdict, *, worker: str = "msa-bot", n: int = 1) -> list[AuditedFinding]:
    out: list[AuditedFinding] = []
    for i in range(n):
        claim = f"clause {i} assertion ({verdict.value})"
        out.append(
            AuditedFinding(
                finding=Finding(worker=worker, clause_ref=str(i), claim=claim, severity="high"),
                verdict=ClaimVerdict(
                    claim=claim,
                    verdict=verdict,
                    confidence=0.95,
                    reason=f"graded {verdict.value}",
                    evidence_quote=_CONTRACT_REF if verdict is not Verdict.UNSUPPORTED else None,
                ),
            )
        )
    return out


def _deliverable(
    specialist: list[AuditedFinding],
    reporter: list[AuditedFinding] | None = None,
    *,
    room: str = "room-test",
) -> RoomAuditResult:
    return RoomAuditResult(
        work_room_id=room,
        audited=tuple(specialist),
        report_summary="test synthesis",
        report_audited=tuple(reporter or ()),
    )


def _hire(worker: str, bid_usdc: float) -> Hire:
    return Hire(worker=worker, price_atomic=usdc(bid_usdc), value=1.0, relevance=1.0)


def _fixed_clock(start: int = 0):
    """A deterministic clock: returns 'T0000', 'T0001', … so timestamps are pinned."""
    n = {"i": start}

    def clock() -> str:
        s = f"T{n['i']:04d}"
        n["i"] += 1
        return s

    return clock


# A fixed private key (32-byte hex) so receipt signing is deterministic in tests.
_TEST_KEY = "0x" + "11" * 32


# ── 1. signed-receipt round-trip ───────────────────────────────────────────────


def test_receipt_roundtrip_verifies_and_tamper_fails():
    """build → sign → verify True; bump a settled amount on the signed receipt → False."""
    gate = _FakeGate()
    deliverable = _deliverable(_audited(Verdict.CONFIRMED, worker="alpha"))
    hires = [_hire("alpha", 0.05)]
    result = asyncio.run(settle_job(gate, deliverable, hires, {"alpha": "0xAAA"}))

    signer = make_receipt_signer(_TEST_KEY)
    receipt = build_receipt("room-test", deliverable, result, timestamp="T0000")
    signed = signer.sign(receipt)

    # An honest signed receipt verifies against its signer address.
    assert verify_receipt(signed) is True

    # Tamper: bump the receipt's first worker line settled amount, keep the OLD signature.
    bad_line = dataclasses.replace(
        signed.receipt.workers[0], settled_atomic=signed.receipt.workers[0].settled_atomic + 1
    )
    bad_receipt = dataclasses.replace(signed.receipt, workers=(bad_line, *signed.receipt.workers[1:]))
    tampered = dataclasses.replace(signed, receipt=bad_receipt)
    assert verify_receipt(tampered) is False


# ── 2. hash-chained ledger ──────────────────────────────────────────────────────


def test_ledger_appends_chain_and_corruption_is_detected():
    """append several events → verify_chain True; corrupt the file → verify_chain False."""
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "ledger.jsonl")
        led = HashChainedLedger(path)
        led.append("verify_ok", {"worker": "alpha"}, timestamp="T0000")
        led.append("before_settle", {"worker": "alpha", "amount": 50_000}, timestamp="T0001")
        led.append("settled", {"worker": "alpha", "tx": "0xfake0"}, timestamp="T0002")
        assert led.verify_chain() is True

        # Corrupt the persisted chain: flip a byte in the middle of the file.
        with open(path, "r", encoding="utf-8") as fh:
            raw = fh.read()
        corrupt = raw.replace("alpha", "EVILX", 1)
        assert corrupt != raw, "fixture should actually change the file"
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(corrupt)

        assert HashChainedLedger(path).verify_chain() is False


# ── 3. hooks → ledger ───────────────────────────────────────────────────────────


def test_hooks_record_settled_events_and_chain_holds():
    """settle_job + a recorder → a 'settled' entry per paid worker; chain verifies."""
    with tempfile.TemporaryDirectory() as d:
        led = HashChainedLedger(os.path.join(d, "ledger.jsonl"))
        rec = ReceiptLedgerRecorder(led, clock=_fixed_clock())

        gate = _FakeGate()
        deliverable = _deliverable(
            _audited(Verdict.CONFIRMED, worker="alpha"), _audited(Verdict.CONFIRMED, worker="beta")
        )
        hires = [_hire("alpha", 0.05), _hire("beta", 0.03)]
        result = asyncio.run(
            settle_job(gate, deliverable, hires, {"alpha": "0xAAA", "beta": "0xBBB"}, hooks=rec)
        )
        assert result.gate_passed is True

        events = [e.event for e in led.entries()]
        # Both workers verified + settled → a verify_ok + before_settle + settled each.
        assert events.count("settled") == 2
        assert events.count("verify_ok") == 2
        assert events.count("before_settle") == 2
        assert "withheld" not in events
        assert led.verify_chain() is True


def test_hooks_record_verify_fail_and_no_settle():
    """A failing verify → a 'verify_fail' entry and NO 'settled'; chain verifies."""
    with tempfile.TemporaryDirectory() as d:
        led = HashChainedLedger(os.path.join(d, "ledger.jsonl"))
        rec = ReceiptLedgerRecorder(led, clock=_fixed_clock())

        gate = _FakeGate(verify_ok=False)
        deliverable = _deliverable(_audited(Verdict.CONFIRMED, worker="alpha"))
        result = asyncio.run(
            settle_job(gate, deliverable, [_hire("alpha", 0.05)], {"alpha": "0xAAA"}, hooks=rec)
        )
        assert result.gate_passed is True  # job cleared the no-fab gate

        events = [e.event for e in led.entries()]
        assert "verify_fail" in events
        assert "settled" not in events
        assert led.verify_chain() is True


# ── 4. the "$0 for fabricated work" trail ───────────────────────────────────────


def test_fabricated_job_trail_is_all_withheld_and_receipt_fails_gate():
    """One UNSUPPORTED claim → withheld entries, NO settled, and receipt.gate_passed False."""
    with tempfile.TemporaryDirectory() as d:
        led = HashChainedLedger(os.path.join(d, "ledger.jsonl"))
        rec = ReceiptLedgerRecorder(led, clock=_fixed_clock())

        gate = _FakeGate()
        # alpha clean, beta fabricated — the lie withholds the WHOLE job.
        deliverable = _deliverable(
            _audited(Verdict.CONFIRMED, worker="alpha"),
            _audited(Verdict.UNSUPPORTED, worker="beta"),
        )
        hires = [_hire("alpha", 0.05), _hire("beta", 0.05)]
        result = asyncio.run(
            settle_job(gate, deliverable, hires, {"alpha": "0xAAA", "beta": "0xBBB"}, hooks=rec)
        )

        assert result.gate_passed is False
        assert gate.settled == []  # no money moved at all

        events = [e.event for e in led.entries()]
        assert events.count("withheld") == 2  # both workers withheld
        assert "settled" not in events

        # The finalized signed receipt records the gate failure and is anchored in the chain.
        signer = make_receipt_signer(_TEST_KEY)
        signed = rec.finalize_receipt("room-test", deliverable, result, signer)
        assert signed.receipt.gate_passed is False
        assert verify_receipt(signed) is True
        assert [e.event for e in led.entries()][-1] == "receipt"
        assert led.verify_chain() is True


# ── 5. backward compatibility: hooks=None unchanged ─────────────────────────────


def test_hooks_none_is_a_noop_and_settlement_unchanged():
    """hooks=None (the default) → settle_job behaves exactly as before, no crash."""
    gate_a = _FakeGate()
    gate_b = _FakeGate()
    deliverable = _deliverable(
        _audited(Verdict.CONFIRMED, worker="alpha"), _audited(Verdict.CONFIRMED, worker="beta")
    )
    hires = [_hire("alpha", 0.05), _hire("beta", 0.03)]
    addrs = {"alpha": "0xAAA", "beta": "0xBBB"}

    without = asyncio.run(settle_job(gate_a, deliverable, hires, addrs))           # implicit None
    with_none = asyncio.run(settle_job(gate_b, deliverable, hires, addrs, hooks=None))

    # Same JobSettlement either way — the gate decision + per-worker money are identical.
    assert without == with_none
    assert without.gate_passed is True
    assert without.total_settled_atomic == without.total_authorized_atomic


def _run_all():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"  ✓ {fn.__name__}")
    print(f"\n{len(fns)} passed")


if __name__ == "__main__":
    _run_all()
