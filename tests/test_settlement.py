"""Settlement-gate tests — the verify→settle money bridge, proven OFFLINE.

`settle_job` turns a graded deliverable into per-worker money movement through an
injected `PaymentGate`. These tests inject a `_FakeGate` (no chain, no keys) and assert
the two locked rules + the ordering invariant:

  1. **No-fabrication hard gate.** A single `UNSUPPORTED` (fabricated) claim anywhere in
     the deliverable withholds the WHOLE job — every worker settles $0 and the gate's
     `settle` is never called ("$0 for fabricated work").
  2. **Per-worker prorate (x402 `upto`).** On a passing job each worker is paid
     ``round(its_bid × pay_fraction)`` to its OWN wallet — never more than its bid.
  3. **verify-before-settle.** Each worker's authorization is verified (no money moves)
     BEFORE it is settled; a verify-fail, a missing wallet, or a settle raise is local
     (recorded with a terminal status, $0) and never aborts the rest of the team.

The `_FakeGate` records every `verify`/`settle` call in one ordered log so a test can
prove verify precedes settle, and records each `settle`'s `(amount_atomic, pay_to)` so a
test can prove the money that moved == the prorated bid to the right wallet.

Run:  PYTHONHASHSEED=1 .venv/bin/python tests/test_settlement.py
"""

from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from agent_exchange.audit.report import AuditedFinding
from agent_exchange.audit.room_audit_types import RoomAuditResult
from agent_exchange.market.hiring_types import Hire
from agent_exchange.metrics import usdc
from agent_exchange.payments.settlement import settle_job
from agent_exchange.payments.types import JobSettlement, PaymentGate
from agent_exchange.verify.schema import LENIENT, ClaimVerdict, Verdict
from agent_exchange.workers.finding import Finding


# ── the injected fake gate ────────────────────────────────────────────────────


class _FakeGate:
    """An in-memory `PaymentGate` — no chain, no keys. Records call order + each settle.

    * `build_requirement` → a plain dict ``{"amount", "pay_to"}`` (opaque pass-through).
    * `authorize` → an opaque dict payload tagged with the wallet it was signed for.
    * `verify` → returns `self.verify_ok` (flip to False to exercise the verify-fail path).
    * `settle` → RECORDS ``(amount_atomic, pay_to)`` into `self.settled` and returns a
      deterministic fake tx hash ``"0xfake<seq>"``.

    `self.calls` is one ordered log of ``("verify"|"settle", pay_to)`` so a test can prove
    verify happened before settle.
    """

    def __init__(self, *, verify_ok: bool = True) -> None:
        self.verify_ok = verify_ok
        self.settled: list[tuple[int, str]] = []      # (amount_atomic, pay_to) per settle
        self.calls: list[tuple[str, str]] = []        # ordered ("verify"|"settle", pay_to)
        self._seq = 0

    def build_requirement(self, *, amount_atomic: int, pay_to: str) -> object:
        return {"amount": amount_atomic, "pay_to": pay_to}

    async def authorize(self, requirement: object) -> object:
        return {"sig": "0xauth", "pay_to": requirement["pay_to"]}  # type: ignore[index]

    async def verify(self, payload: object, requirement: object) -> bool:
        self.calls.append(("verify", requirement["pay_to"]))       # type: ignore[index]
        return self.verify_ok

    async def settle(self, payload: object, requirement: object, *, amount_atomic: int) -> str:
        pay_to = requirement["pay_to"]                             # type: ignore[index]
        self.calls.append(("settle", pay_to))
        self.settled.append((amount_atomic, pay_to))
        tx = f"0xfake{self._seq}"
        self._seq += 1
        return tx


# ── deliverable / hire builders ───────────────────────────────────────────────

_CONTRACT_REF = "Vendor's aggregate liability is capped at the prior 12 months' fees."


def _audited(verdict: Verdict, *, worker: str = "msa-bot", n: int = 1) -> list[AuditedFinding]:
    """`n` `AuditedFinding`s all carrying `verdict` (high-confidence, so never escalated)."""
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


def _deliverable(specialist: list[AuditedFinding], reporter: list[AuditedFinding] | None = None) -> RoomAuditResult:
    """A `RoomAuditResult` whose `all_audited` == specialist findings + reporter claims."""
    return RoomAuditResult(
        work_room_id="room-test",
        audited=tuple(specialist),
        report_summary="test synthesis",
        report_audited=tuple(reporter or ()),
    )


def _hire(worker: str, bid_usdc: float) -> Hire:
    return Hire(worker=worker, price_atomic=usdc(bid_usdc), value=1.0, relevance=1.0)


def _settle(gate, deliverable, hires, payout_addresses, *, policy=LENIENT) -> JobSettlement:
    return asyncio.run(settle_job(gate, deliverable, hires, payout_addresses, policy=policy))


def _by_worker(result: JobSettlement) -> dict[str, object]:
    return {w.worker: w for w in result.workers}


# ── tests ──────────────────────────────────────────────────────────────────────


def test_all_confirmed_pays_each_worker_its_full_bid():
    """ALL CONFIRMED → gate passes, pay_fraction 1.0, each worker settled == its bid."""
    gate = _FakeGate()
    # Two workers, each with one confirmed finding → all confirmed → pay_fraction 1.0.
    deliverable = _deliverable(_audited(Verdict.CONFIRMED, worker="alpha"), _audited(Verdict.CONFIRMED, worker="beta"))
    hires = [_hire("alpha", 0.05), _hire("beta", 0.03)]
    addrs = {"alpha": "0xAAA", "beta": "0xBBB"}

    result = _settle(gate, deliverable, hires, addrs)

    assert result.gate_passed is True
    assert abs(result.pay_fraction - 1.0) < 1e-9
    assert result.n_unsupported == 0
    ws = _by_worker(result)
    # Each worker settled its FULL bid, to its OWN wallet, with a tx, status "settled".
    assert ws["alpha"].settled_atomic == usdc(0.05) == ws["alpha"].authorized_atomic
    assert ws["beta"].settled_atomic == usdc(0.03) == ws["beta"].authorized_atomic
    assert ws["alpha"].status == ws["beta"].status == "settled"
    assert ws["alpha"].tx_hash and ws["beta"].tx_hash
    # One settle per worker, recorded to the right wallet for the right amount.
    assert len(gate.settled) == 2
    assert (usdc(0.05), "0xAAA") in gate.settled
    assert (usdc(0.03), "0xBBB") in gate.settled
    # Money invariant: full pay ⇒ nothing withheld, settled == authorized.
    assert result.total_settled_atomic == result.total_authorized_atomic
    assert result.total_withheld_atomic == 0


def test_one_partial_prorates_each_worker_below_its_bid_under_lenient():
    """ONE PARTIAL (no unsupported) → gate passes, LENIENT half-credit prorate < bid."""
    gate = _FakeGate()
    # 2 claims: one confirmed (1.0) + one partial (0.5 under LENIENT) → mean 0.75.
    deliverable = _deliverable(
        _audited(Verdict.CONFIRMED, worker="alpha") + _audited(Verdict.PARTIAL, worker="alpha")
    )
    hires = [_hire("alpha", 0.08)]
    addrs = {"alpha": "0xAAA"}

    result = _settle(gate, deliverable, hires, addrs, policy=LENIENT)

    assert result.gate_passed is True
    assert result.n_unsupported == 0
    assert abs(result.pay_fraction - 0.75) < 1e-9       # (1.0 + 0.5) / 2
    w = _by_worker(result)["alpha"]
    expected = round(usdc(0.08) * 0.75)
    assert w.settled_atomic == expected
    assert w.settled_atomic < w.authorized_atomic        # prorated strictly below the bid
    assert w.status == "settled"
    assert gate.settled == [(expected, "0xAAA")]


def test_one_unsupported_withholds_whole_job_and_never_settles():
    """ONE UNSUPPORTED (fabrication) → gate False, EVERY worker withheld, settle never called."""
    gate = _FakeGate()
    # alpha is clean, beta fabricated — the lie withholds the WHOLE job, alpha included.
    deliverable = _deliverable(
        _audited(Verdict.CONFIRMED, worker="alpha"),
        _audited(Verdict.UNSUPPORTED, worker="beta"),
    )
    hires = [_hire("alpha", 0.05), _hire("beta", 0.05)]
    addrs = {"alpha": "0xAAA", "beta": "0xBBB"}

    result = _settle(gate, deliverable, hires, addrs)

    assert result.gate_passed is False
    assert result.n_unsupported == 1
    assert result.pay_fraction == 0.0                    # reported 0 when the gate fails
    ws = _by_worker(result)
    # EVERY worker withheld: $0 settled, no tx, status "withheld" — even clean alpha.
    for w in ws.values():
        assert w.settled_atomic == 0
        assert w.tx_hash is None
        assert w.status == "withheld"
    # The gate's settle was NEVER called — no money moved at all.
    assert gate.settled == []
    assert not any(c[0] == "settle" for c in gate.calls)
    assert result.total_settled_atomic == 0
    assert result.total_withheld_atomic == result.total_authorized_atomic


def test_verify_failure_withholds_only_that_worker():
    """VERIFY FAILS → that worker status 'verify_failed', $0, not settled."""
    gate = _FakeGate(verify_ok=False)
    deliverable = _deliverable(_audited(Verdict.CONFIRMED, worker="alpha"))
    hires = [_hire("alpha", 0.05)]
    addrs = {"alpha": "0xAAA"}

    result = _settle(gate, deliverable, hires, addrs)

    # The job CLEARED the no-fab gate, but the authorization didn't verify → no settle.
    assert result.gate_passed is True
    w = _by_worker(result)["alpha"]
    assert w.status == "verify_failed"
    assert w.settled_atomic == 0
    assert w.tx_hash is None
    assert gate.settled == []                            # verify gate stops the settle


def test_missing_payout_address_withholds_only_that_worker():
    """MISSING payout address → that worker 'withheld'; others settle unaffected."""
    gate = _FakeGate()
    deliverable = _deliverable(_audited(Verdict.CONFIRMED, worker="alpha", n=1) + _audited(Verdict.CONFIRMED, worker="beta", n=1))
    hires = [_hire("alpha", 0.05), _hire("beta", 0.04)]
    addrs = {"alpha": "0xAAA"}                            # beta has NO payout wallet

    result = _settle(gate, deliverable, hires, addrs)

    assert result.gate_passed is True
    ws = _by_worker(result)
    # beta: no wallet → withheld, $0, never built a requirement / settle for it.
    assert ws["beta"].status == "withheld"
    assert ws["beta"].settled_atomic == 0
    assert ws["beta"].pay_to == ""
    # alpha: unaffected — settled its full bid to its wallet.
    assert ws["alpha"].status == "settled"
    assert ws["alpha"].settled_atomic == usdc(0.05)
    assert gate.settled == [(usdc(0.05), "0xAAA")]       # exactly one settle, beta absent


def test_verify_precedes_settle_for_each_worker():
    """verify-before-settle ordering: each worker's verify precedes its settle in the log."""
    gate = _FakeGate()
    deliverable = _deliverable(_audited(Verdict.CONFIRMED, worker="alpha"), _audited(Verdict.CONFIRMED, worker="beta"))
    hires = [_hire("alpha", 0.05), _hire("beta", 0.05)]
    addrs = {"alpha": "0xAAA", "beta": "0xBBB"}

    _settle(gate, deliverable, hires, addrs)

    # For every wallet that settled, its verify call comes strictly before its settle call.
    for _, pay_to in gate.settled:
        verify_idx = gate.calls.index(("verify", pay_to))
        settle_idx = gate.calls.index(("settle", pay_to))
        assert verify_idx < settle_idx, f"verify must precede settle for {pay_to}"
    # And the very first recorded call is a verify, never a settle (nothing settles unverified).
    assert gate.calls[0][0] == "verify"


# ── JobSettlement property checks ───────────────────────────────────────────────


def test_job_settlement_money_properties_on_partial_pay():
    """total_settled / withheld / authorized agree on a prorated (partial-pay) job."""
    gate = _FakeGate()
    deliverable = _deliverable(
        _audited(Verdict.CONFIRMED, worker="alpha") + _audited(Verdict.PARTIAL, worker="alpha")
    )
    hires = [_hire("alpha", 0.08)]
    result = _settle(gate, deliverable, hires, {"alpha": "0xAAA"}, policy=LENIENT)

    expected_settled = round(usdc(0.08) * 0.75)
    assert result.total_authorized_atomic == usdc(0.08)
    assert result.total_settled_atomic == expected_settled
    # The identity that the on-chain split must satisfy: authorized = settled + withheld.
    assert result.total_withheld_atomic == result.total_authorized_atomic - result.total_settled_atomic
    assert result.total_withheld_atomic > 0


def test_job_settlement_money_properties_on_full_withhold():
    """On a fabricated job: settled 0, withheld == authorized, authorized = sum of bids."""
    gate = _FakeGate()
    deliverable = _deliverable(
        _audited(Verdict.CONFIRMED, worker="alpha"),
        _audited(Verdict.UNSUPPORTED, worker="beta"),
    )
    hires = [_hire("alpha", 0.05), _hire("beta", 0.03)]
    result = _settle(gate, deliverable, hires, {"alpha": "0xAAA", "beta": "0xBBB"})

    assert result.total_authorized_atomic == usdc(0.05) + usdc(0.03)
    assert result.total_settled_atomic == 0
    assert result.total_withheld_atomic == result.total_authorized_atomic


def test_fakegate_satisfies_payment_gate_protocol():
    """The fake honours the injected seam — `_FakeGate` IS a `PaymentGate`."""
    assert isinstance(_FakeGate(), PaymentGate)


def _run_all():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"  ✓ {fn.__name__}")
    print(f"\n{len(fns)} passed")


if __name__ == "__main__":
    _run_all()
