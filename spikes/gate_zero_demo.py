"""Gate-->$0 demo (offline) — emit the Paper B Table T3 data.

Runs `settle_job` through an in-memory fake gate for two scenarios and records the
no-fabrication gate decision + the money that actually moved:

  * CLEAN job  (all claims confirmed)        → gate_passed=True,  settle called, paid in full.
  * ONE-FAB job (one unsupported among them)  → gate_passed=False, settle NEVER called, $0.

This is the offline twin of `tests/test_settlement.py` (same logic) and the source for
`data/eval/gate_zero_table.json` (rendered by `scripts/paper_figs.py::table_B_T3_gate_zero`).
No chain, no keys, deterministic.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from agent_exchange.audit.report import AuditedFinding
from agent_exchange.audit.room_audit_types import RoomAuditResult
from agent_exchange.market.hiring_types import Hire
from agent_exchange.metrics import usdc
from agent_exchange.payments.settlement import settle_job
from agent_exchange.verify.schema import STRICT, ClaimVerdict, Verdict
from agent_exchange.workers.finding import Finding

_CONTRACT = "Vendor's aggregate liability is capped at the prior 12 months' fees."


class _FakeGate:
    """In-memory PaymentGate — records settle calls; no chain, no keys."""

    def __init__(self) -> None:
        self.settle_calls = 0

    def build_requirement(self, *, amount_atomic: int, pay_to: str):
        return {"amount": amount_atomic, "pay_to": pay_to}

    async def authorize(self, requirement):
        return {"sig": "0xauth", "pay_to": requirement["pay_to"]}

    async def verify(self, payload, requirement) -> bool:
        return True

    async def settle(self, payload, requirement, *, amount_atomic: int) -> str:
        self.settle_calls += 1
        return f"0xfake{self.settle_calls}"


def _finding(worker: str, verdict: Verdict, i: int) -> AuditedFinding:
    claim = f"clause {i} assertion ({verdict.value})"
    return AuditedFinding(
        finding=Finding(worker=worker, clause_ref=str(i), claim=claim, severity="high"),
        verdict=ClaimVerdict(claim=claim, verdict=verdict, confidence=0.95, reason="",
                             evidence_quote=_CONTRACT if verdict is not Verdict.UNSUPPORTED else None),
    )


def _deliverable(verdicts: list[Verdict]) -> RoomAuditResult:
    return RoomAuditResult(
        work_room_id="room-demo",
        audited=tuple(_finding("alpha", v, i) for i, v in enumerate(verdicts)),
        report_summary="", report_audited=(),
    )


def _run(verdicts: list[Verdict]) -> dict:
    gate = _FakeGate()
    deliverable = _deliverable(verdicts)
    hires = [Hire(worker="alpha", price_atomic=usdc(0.05), value=1.0, relevance=1.0)]
    result = asyncio.run(settle_job(gate, deliverable, hires, {"alpha": "0xAAA"}, policy=STRICT))
    return {
        "gate_passed": result.gate_passed,
        "n_unsupported": result.n_unsupported,
        "settle_called": gate.settle_calls,
        "pay_fraction": result.pay_fraction,
        "total_settled_usdc": result.total_settled_atomic / 1_000_000,
        "total_authorized_usdc": result.total_authorized_atomic / 1_000_000,
    }


def main() -> None:
    clean = _run([Verdict.CONFIRMED, Verdict.CONFIRMED])
    one_fab = _run([Verdict.CONFIRMED, Verdict.UNSUPPORTED])
    table = [
        {"scenario": "clean job (all confirmed)", **clean},
        {"scenario": "one fabricated claim", **one_fab},
    ]
    for row in table:
        print(f"  {row['scenario']:28s} gate_passed={row['gate_passed']!s:5s} "
              f"settle_called={row['settle_called']} paid=${row['total_settled_usdc']:.4f}")
    out = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data", "eval", "gate_zero_table.json"))
    os.makedirs(os.path.dirname(out), exist_ok=True)
    json.dump({"policy": "strict", "rows": table}, open(out, "w"), indent=2)
    print(f"\n  table → {out}")


if __name__ == "__main__":
    main()
