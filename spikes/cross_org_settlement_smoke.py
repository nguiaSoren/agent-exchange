"""LIVE cross-ORG settlement smoke — prove real USDC crosses OWNER boundaries on Base Sepolia.

The plain `settlement_smoke.py` proves "you only pay for verified work" by paying each
worker to its own wallet. This spike sharpens it for the Band story's #1 primitive —
*agents you don't own* — by settling two workers owned by TWO DIFFERENT owners to TWO
DIFFERENT wallets in one job, and TIMING the settlement leg:

  • owner A  (agent-exchange / you)        worker "liability-auditor"  → SELLER_PAYTO_ADDRESS
  • owner B  (babidibuu19, cross-owner)    worker "tax-clause-bot"     → OWNER2_PAYTO_ADDRESS

Both findings are CONFIRMED, so the no-fabrication gate passes and BOTH coins move — one to
each owner. The result is two real Base Sepolia transactions to two distinct addresses: hard,
verifiable proof that the market settles a cross-owner hire across an org boundary, not just
within one wallet. Settlement wall-time is measured (monotonic) and reported.

It NEVER crashes and NEVER spends without keys. Bids are tiny (0.01–0.03 USDC).

    cd agent-exchange
    .venv/bin/python spikes/cross_org_settlement_smoke.py

Env contract (read from `.env`):
  - `EVM_PRIVATE_KEY`        — the buyer (owner A) wallet that signs + funds settlement.
  - `SELLER_PAYTO_ADDRESS`   — owner A's receiving wallet (the auditor's payout).
  - `OWNER2_PAYTO_ADDRESS`   — owner B's receiving wallet (the cross-owner agent's payout).
  - `X402_FACILITATOR_URL` / `X402_NETWORK` / `X402_USDC_ADDRESS` — as in settlement_smoke.py.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from dotenv import load_dotenv

from agent_exchange.audit.report import AuditedFinding
from agent_exchange.audit.room_audit_types import RoomAuditResult
from agent_exchange.market.hiring_types import Hire
from agent_exchange.metrics import usdc
from agent_exchange.payments.settlement import settle_job
from agent_exchange.payments.x402_gate import make_x402_gate
from agent_exchange.verify.schema import STRICT, ClaimVerdict, Verdict
from agent_exchange.workers.finding import Finding

load_dotenv("/Users/soren/Desktop/BAND HACKATHON/agent-exchange/.env")

EXPLORER = "https://sepolia.basescan.org/tx/"

# Two workers, two OWNERS. The cross-owner agent (owner B) is the one you don't own.
OWNER_A = "agent-exchange"      # you
OWNER_B = "babidibuu19"         # cross-owner (matches BAND_OWNER2_TAX_HANDLE)
WORKER_A = "liability-auditor"  # owner A
WORKER_B = "tax-clause-bot"     # owner B (cross-owner)

HIRES = [
    Hire(worker=WORKER_A, price_atomic=usdc(0.02), value=1.0, relevance=1.0),
    Hire(worker=WORKER_B, price_atomic=usdc(0.01), value=1.0, relevance=1.0),
]

_REF = "Vendor's aggregate liability is capped at the prior 12 months' fees."


def _audited(worker: str) -> AuditedFinding:
    """One CONFIRMED finding for `worker` (high-confidence, real evidence quote)."""
    claim = f"{worker}: clause assertion (confirmed)"
    return AuditedFinding(
        finding=Finding(worker=worker, clause_ref="3", claim=claim, severity="high"),
        verdict=ClaimVerdict(
            claim=claim, verdict=Verdict.CONFIRMED, confidence=0.95,
            reason="graded confirmed", evidence_quote=_REF,
        ),
    )


def _deliverable_for(worker: str) -> RoomAuditResult:
    """A single-worker CONFIRMED deliverable (gate passes → that worker is paid)."""
    return RoomAuditResult(
        work_room_id=f"cross-org-settlement-{worker}",
        audited=(_audited(worker),),
        report_summary="cross-org settlement smoke",
        report_audited=(),
    )


async def _main() -> None:
    pk = (os.getenv("EVM_PRIVATE_KEY") or "").strip()
    seller = (os.getenv("SELLER_PAYTO_ADDRESS") or "").strip()
    owner2 = (os.getenv("OWNER2_PAYTO_ADDRESS") or "").strip()
    if not pk:
        print("No EVM_PRIVATE_KEY — fund a buyer wallet at faucet.circle.com (Base Sepolia). Exiting without spending.")
        return
    if not (seller and owner2):
        print("Need BOTH SELLER_PAYTO_ADDRESS (owner A) and OWNER2_PAYTO_ADDRESS (owner B) in .env. Exiting without spending.")
        return
    if seller.lower() == owner2.lower():
        print("SELLER_PAYTO_ADDRESS == OWNER2_PAYTO_ADDRESS — not cross-org. Set a distinct owner-2 wallet. Exiting.")
        return

    payout = {WORKER_A: seller, WORKER_B: owner2}

    gate = make_x402_gate(
        pk,
        facilitator_url=os.getenv("X402_FACILITATOR_URL", "https://x402.org/facilitator"),
        network=os.getenv("X402_NETWORK", "eip155:84532"),
        asset_address=os.getenv("X402_USDC_ADDRESS", "0x036CbD53842c5426634e7929541eC2318f3dCF7e"),
    )
    try:
        await gate.ensure_permit2_approval()
    except Exception as exc:  # noqa: BLE001
        print(f"permit2 approval failed: {exc}  (buyer likely needs Base Sepolia ETH for gas or test USDC)")
        return

    print("\nLIVE cross-ORG settlement — Base Sepolia")
    print(f"  owner A: {OWNER_A:<16} worker {WORKER_A:<18} → {seller}")
    print(f"  owner B: {OWNER_B:<16} worker {WORKER_B:<18} → {owner2}   (cross-owner)")

    # Settle each owner in its OWN call, spaced so the buyer's nonce advances between
    # transactions. Back-to-back sends from one wallet race the nonce and the facilitator
    # rejects the second ("invalid_exact_evm_transaction"). A gap lets tx1 mine first.
    legs = [(OWNER_A, WORKER_A, seller, HIRES[0], False),
            (OWNER_B, WORKER_B, owner2, HIRES[1], True)]
    settled_workers = []
    distinct = set()
    for i, (owner, worker, addr, hire, is_cross) in enumerate(legs):
        if i > 0:
            await asyncio.sleep(15)  # let the previous tx mine + nonce advance
        t0 = time.monotonic_ns()
        try:
            r = await settle_job(gate, _deliverable_for(worker), [hire], {worker: addr}, policy=STRICT)
            ws = r.workers[0]
            leg_ms = (time.monotonic_ns() - t0) / 1e6
            status, settled, tx = ws.status, ws.settled_atomic / 10**6, ws.tx_hash or ""
        except Exception as exc:  # noqa: BLE001
            leg_ms = (time.monotonic_ns() - t0) / 1e6
            status, settled, tx = f"error: {exc}", 0.0, ""
        if status == "settled":
            distinct.add(addr.lower())
        line = f"  • {owner}/{worker:<18} settled={settled:.3f} USDC → {addr}  [{status}]"
        if tx:
            line += f"\n      tx: {EXPLORER}{tx}"
        print(line)
        settled_workers.append({"owner": owner, "worker": worker, "pay_to": addr,
                                "cross_owner": is_cross, "settled_usdc": round(settled, 6),
                                "status": status, "tx": tx, "leg_ms": round(leg_ms, 1),
                                "explorer": (EXPLORER + tx) if tx else ""})

    total = sum(w["settled_usdc"] for w in settled_workers)
    print(f"\nCROSS-ORG: {len(distinct)} distinct owner wallets paid.  total {total:.3f} USDC across owners.")

    evidence = {
        "kind": "cross-org-settlement",
        "network": os.getenv("X402_NETWORK", "eip155:84532"),
        "distinct_owner_wallets": len(distinct),
        "workers": settled_workers,
        "total_settled_usdc": round(total, 6),
    }
    out = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data", "eval", "cross_org_settlement_evidence.json"))
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w") as f:
        json.dump(evidence, f, indent=2)
    print(f"\n  evidence → {out}")


if __name__ == "__main__":
    asyncio.run(_main())
