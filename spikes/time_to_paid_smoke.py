"""End-to-end TIME-TO-PAID — one real job, post → USDC in a worker's wallet, timed.

Closes the known gap in METRICS_LOCK ("time-to-paid: not yet measured as a single timed
end-to-end job"). It runs the REAL work leg (live specialists audit a contract + a live
verifier grades every claim) and the REAL settle leg (x402 on Base Sepolia moves a testnet
coin to the worker's wallet), wrapping the whole thing in one monotonic clock:

    t_post → [ audit: fan specialists + grade on live models ] → [ settle on-chain ] → t_paid

and prints time-to-paid = (t_paid − t_post). Both legs are real; the number is dominated by
the work leg (model latency), with on-chain settlement a few seconds on top.

Needs (in .env): OPENAI_API_KEY (specialists), AIMLAPI_API_KEY (verifier), EVM_PRIVATE_KEY
(funded buyer), SELLER_PAYTO_ADDRESS (payout). Settles ONE worker (one clean tx — avoids the
nonce race two back-to-back sends hit). Bid is tiny (0.01 USDC).

    cd agent-exchange && .venv/bin/python spikes/time_to_paid_smoke.py
"""

from __future__ import annotations

import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import httpx
from dotenv import load_dotenv

from agent_exchange.audit.pipeline import audit
from agent_exchange.audit.room_audit_types import RoomAuditResult
from agent_exchange.core import make_backend
from agent_exchange.market.hiring_types import Hire
from agent_exchange.metrics import usdc
from agent_exchange.payments.settlement import settle_job
from agent_exchange.payments.x402_gate import make_x402_gate
from agent_exchange.verify import Verifier
from agent_exchange.verify.schema import Verdict
from agent_exchange.workers.pool import AuditPool
from agent_exchange.workers.specialist import make_pool_specialists

load_dotenv("/Users/soren/Desktop/BAND HACKATHON/agent-exchange/.env")
EXPLORER = "https://sepolia.basescan.org/tx/"

CONTRACT = """
MASTER SERVICES AGREEMENT

3. Limitation of Liability. Vendor's aggregate liability under this Agreement shall not
   exceed the total fees paid by Customer in the twelve (12) months preceding the event
   giving rise to the claim. Neither party is liable for indirect, incidental, or
   consequential damages.

5. Term and Termination. This Agreement continues for one (1) year, renewing automatically
   unless either party gives sixty (60) days' written notice of non-renewal. Either party
   may terminate for material breach uncured thirty (30) days after written notice.

7. Data Protection. Vendor shall notify Customer of a personal-data breach without undue
   delay and in any event within 72 hours.
""".strip()


async def main() -> None:
    for k in ("OPENAI_API_KEY", "AIMLAPI_API_KEY", "EVM_PRIVATE_KEY", "SELLER_PAYTO_ADDRESS"):
        if not (os.getenv(k) or "").strip():
            print(f"{k} not set in .env — cannot run the real end-to-end. Exiting without spending.")
            return

    audit_model = os.getenv("OPENAI_AUDIT_MODEL", "gpt-4.1-mini")
    verifier_model = os.getenv("AIMLAPI_VERIFIER_MODEL", "gpt-4.1-2025-04-14")
    pool = AuditPool(make_pool_specialists("openai", audit_model))
    verifier = Verifier(make_backend("openai", verifier_model))
    print(f"specialists {audit_model} · verifier {verifier_model}\n")

    # ── t_post: the job opens ───────────────────────────────────────────────
    t_post = time.monotonic_ns()

    # ── WORK leg: live specialists audit the contract + live verifier grades ─
    try:
        report = await audit(CONTRACT, contract_id="ttp-msa", pool=pool,
                             verifier=verifier, authorized_atomic=usdc(0.05))
    except httpx.HTTPStatusError as e:
        print(f"live audit failed: HTTP {e.response.status_code} — see provider. Exiting.")
        return
    t_work = time.monotonic_ns()

    # Pick ONE worker whose findings are all CONFIRMED (a clean PAID leg).
    by_worker: dict[str, list] = {}
    for af in report.audited:
        by_worker.setdefault(af.finding.worker, []).append(af)
    worker = next((w for w, afs in by_worker.items()
                   if afs and all(af.verdict.verdict is Verdict.CONFIRMED for af in afs)), None)
    if worker is None:
        print("no fully-confirmed worker this run (verifier graded everything partial/unsupported); "
              "re-run for a clean PAID leg. Work leg was real; skipping on-chain settle.")
        print(f"  work leg: {(t_work - t_post) / 1e9:.1f}s")
        return

    deliverable = RoomAuditResult(
        work_room_id="time-to-paid", audited=tuple(by_worker[worker]),
        report_summary="time-to-paid smoke", report_audited=(),
    )
    hires = [Hire(worker=worker, price_atomic=usdc(0.01), value=1.0, relevance=1.0)]
    payout = {worker: os.getenv("SELLER_PAYTO_ADDRESS").strip()}

    # ── SETTLE leg: real x402 settlement on Base Sepolia ────────────────────
    gate = make_x402_gate(
        os.getenv("EVM_PRIVATE_KEY").strip(),
        facilitator_url=os.getenv("X402_FACILITATOR_URL", "https://x402.org/facilitator"),
        network=os.getenv("X402_NETWORK", "eip155:84532"),
        asset_address=os.getenv("X402_USDC_ADDRESS", "0x036CbD53842c5426634e7929541eC2318f3dCF7e"),
    )
    try:
        await gate.ensure_permit2_approval()
        settlement = await settle_job(gate, deliverable, hires, payout)
    except Exception as exc:  # noqa: BLE001
        print(f"settle failed: {exc}. Work leg was real ({(t_work - t_post) / 1e9:.1f}s).")
        return
    t_paid = time.monotonic_ns()

    work_s = (t_work - t_post) / 1e9
    settle_s = (t_paid - t_work) / 1e9
    ttp_s = (t_paid - t_post) / 1e9
    w0 = settlement.workers[0]
    print(f"WORKER {worker}: settled {w0.settled_atomic / 10**6:.3f} USDC [{w0.status}]")
    if w0.tx_hash:
        print(f"  tx: {EXPLORER}{w0.tx_hash}")
    print(f"\n⏱  TIME-TO-PAID: {ttp_s:.1f}s  (work {work_s:.1f}s on live models + settle {settle_s:.1f}s on-chain)")
    print(f"   = job posted → USDC in the worker's wallet on Base Sepolia (testnet), one real timed run.")


if __name__ == "__main__":
    asyncio.run(main())
