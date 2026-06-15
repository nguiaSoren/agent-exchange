"""LIVE settlement-gate smoke — run `settle_job` through the REAL x402 gate on Base Sepolia.

This is the on-chain counterpart to `tests/test_settlement.py` (which proves the same
verify→settle logic OFFLINE on a `_FakeGate`). Here a real `X402Gate` — the buyer's
signer + the public facilitator + Base Sepolia USDC — moves actual testnet coins to each
worker's payout wallet, proving "you only pay for verified work" end-to-end:

  1. build a real `X402Gate` from `EVM_PRIVATE_KEY` + the facilitator/network/asset env;
  2. `ensure_permit2_approval()` once (the gate's allowance to pull USDC for settlement);
  3. build a SMALL graded deliverable — either a tiny hand-made `RoomAuditResult`, or, if
     specialist Band keys + a model are present, chain from a real `collaborate_in_room`;
  4. build 1–2 `Hire`s with SMALL bids (0.01–0.10 USDC) + payout wallets from env;
  5. run `settle_job` and print the gate decision, the prorate, and each worker's
     `(authorized, settled, tx_hash, status)` with its Base Sepolia explorer link.

It is NOT run by the test suite — the orchestrator runs it by hand when a funded buyer
wallet + payout addresses are configured. It NEVER crashes and NEVER spends without keys.

    cd agent-exchange
    .venv/bin/python spikes/settlement_smoke.py

Env contract (read from `.env`):
  - `EVM_PRIVATE_KEY`            — the buyer wallet that signs + funds settlement. With it
                                    UNSET the spike prints a setup hint and exits cleanly
                                    (never spends). Fund it with test USDC at
                                    faucet.circle.com (Base Sepolia).
  - `X402_FACILITATOR_URL`      — public testnet facilitator (default https://x402.org/facilitator).
  - `X402_NETWORK`              — default eip155:84532 (Base Sepolia).
  - `X402_USDC_ADDRESS`         — Base Sepolia test USDC (6 decimals, EIP-3009).
  - `PAYOUT_<WORKER>_ADDRESS`   — per-worker payout wallet (e.g. `PAYOUT_ALPHA_ADDRESS`),
                                    UPPER-cased worker name. Falls back to
                                    `SELLER_PAYTO_ADDRESS` for any worker without its own.
                                    With NO payout address at all, exits cleanly.
  - `SETTLEMENT_SMOKE_FABRICATE=1` — optional: seed one UNSUPPORTED claim to demo the
                                    no-fabrication gate (everyone withheld, $0 moves).

Bids are kept tiny (0.01–0.10 USDC) so a real testnet coin moves cheaply.
"""

from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from dotenv import load_dotenv

from agent_exchange.audit.report import AuditedFinding
from agent_exchange.audit.room_audit_types import RoomAuditResult
from agent_exchange.market.hiring_types import Hire
from agent_exchange.metrics import usdc
from agent_exchange.payments.settlement import settle_job
from agent_exchange.payments.x402_gate import make_x402_gate
from agent_exchange.verify.schema import LENIENT, ClaimVerdict, Verdict
from agent_exchange.workers.finding import Finding

# Explicit path — load_dotenv() with no path can miss depending on cwd.
load_dotenv("/Users/soren/Desktop/BAND HACKATHON/agent-exchange/.env")

EXPLORER = "https://sepolia.basescan.org/tx/"

# A tiny two-worker team with small bids — cheap real testnet coin movement.
HIRES = [
    Hire(worker="alpha", price_atomic=usdc(0.02), value=1.0, relevance=1.0),
    Hire(worker="beta", price_atomic=usdc(0.01), value=1.0, relevance=1.0),
]

_CONTRACT_REF = "Vendor's aggregate liability is capped at the prior 12 months' fees."


def _audited(worker: str, verdict: Verdict) -> AuditedFinding:
    """One graded finding for `worker` carrying `verdict` (high-confidence)."""
    claim = f"{worker}: clause assertion ({verdict.value})"
    return AuditedFinding(
        finding=Finding(worker=worker, clause_ref="1", claim=claim, severity="high"),
        verdict=ClaimVerdict(
            claim=claim,
            verdict=verdict,
            confidence=0.95,
            reason=f"graded {verdict.value}",
            evidence_quote=_CONTRACT_REF if verdict is not Verdict.UNSUPPORTED else None,
        ),
    )


def _build_deliverable(*, fabricate: bool) -> RoomAuditResult:
    """A small hand-made deliverable. By default both findings are confirmed (full pay);
    with `fabricate`, beta's claim is UNSUPPORTED → the no-fab gate withholds everyone."""
    alpha = _audited("alpha", Verdict.CONFIRMED)
    beta = _audited("beta", Verdict.UNSUPPORTED if fabricate else Verdict.PARTIAL)
    return RoomAuditResult(
        work_room_id="settlement-smoke",
        audited=(alpha, beta),
        report_summary="settlement smoke — hand-made deliverable",
        report_audited=(),
    )


def _payout_addresses(workers: list[str]) -> dict[str, str]:
    """`PAYOUT_<WORKER>_ADDRESS` per worker, falling back to `SELLER_PAYTO_ADDRESS`."""
    fallback = (os.getenv("SELLER_PAYTO_ADDRESS") or "").strip()
    addrs: dict[str, str] = {}
    for w in workers:
        specific = (os.getenv(f"PAYOUT_{w.upper()}_ADDRESS") or "").strip()
        addr = specific or fallback
        if addr:
            addrs[w] = addr
    return addrs


async def _main() -> None:
    pk = (os.getenv("EVM_PRIVATE_KEY") or "").strip()
    if not pk:
        print(
            "No EVM_PRIVATE_KEY set. Generate a throwaway buyer wallet, fund it with test "
            "USDC at faucet.circle.com (Base Sepolia), and set EVM_PRIVATE_KEY in .env. "
            "Exiting without spending."
        )
        return

    payout = _payout_addresses([h.worker for h in HIRES])
    if not payout:
        print(
            "No payout address. Set PAYOUT_ALPHA_ADDRESS / PAYOUT_BETA_ADDRESS (per worker) "
            "or SELLER_PAYTO_ADDRESS (shared fallback) in .env. Exiting without spending."
        )
        return

    fabricate = (os.getenv("SETTLEMENT_SMOKE_FABRICATE") or "").strip() in ("1", "true", "yes")

    # Build the REAL gate from the buyer's key + the network/asset/facilitator config.
    gate = make_x402_gate(
        pk,
        facilitator_url=os.getenv("X402_FACILITATOR_URL", "https://x402.org/facilitator"),
        network=os.getenv("X402_NETWORK", "eip155:84532"),
        asset_address=os.getenv("X402_USDC_ADDRESS", "0x036CbD53842c5426634e7929541eC2318f3dCF7e"),
    )

    # One-time allowance so the gate can pull USDC for settlement.
    try:
        await gate.ensure_permit2_approval()
    except Exception as exc:  # noqa: BLE001 — surface, never crash the spike
        print(f"permit2 approval failed: {exc}")
        print("  (most likely the buyer wallet has no Base Sepolia ETH for gas, or no test USDC)")
        return

    deliverable = _build_deliverable(fabricate=fabricate)
    n_unsupported = sum(af.verdict.verdict is Verdict.UNSUPPORTED for af in deliverable.all_audited)

    print("\nLIVE settlement smoke — Base Sepolia")
    print(f"  network={os.getenv('X402_NETWORK', 'eip155:84532')}  facilitator={os.getenv('X402_FACILITATOR_URL', 'https://x402.org/facilitator')}")
    print(f"  deliverable: {len(deliverable.all_audited)} graded claims, {n_unsupported} unsupported"
          f"{'  (fabrication seeded — expect a FULL withhold)' if fabricate else ''}")
    for h in HIRES:
        addr = payout.get(h.worker, "—")
        print(f"  hire: {h.worker:<6} bid={h.price_atomic / 10**6:.3f} USDC → {addr}")

    try:
        result = await settle_job(gate, deliverable, HIRES, payout, policy=LENIENT)
    except Exception as exc:  # noqa: BLE001
        print(f"\nsettle_job raised: {exc}")
        return

    print(f"\nGATE: {'PASSED' if result.gate_passed else 'FAILED (fabrication present — all withheld)'}")
    print(f"  pay_fraction={result.pay_fraction:.3f}  n_unsupported={result.n_unsupported}")
    print("\nPER-WORKER SETTLEMENT (authorized / settled / status / tx):")
    for w in result.workers:
        auth = w.authorized_atomic / 10**6
        settled = w.settled_atomic / 10**6
        line = f"  • {w.worker:<6} auth={auth:.3f}  settled={settled:.3f} USDC  [{w.status}]"
        if w.tx_hash:
            line += f"\n        tx: {EXPLORER}{w.tx_hash}"
        print(line)

    total_settled = result.total_settled_atomic / 10**6
    total_auth = result.total_authorized_atomic / 10**6
    print(
        f"\nTOTAL: {total_settled:.3f} / {total_auth:.3f} USDC settled "
        f"({result.total_withheld_atomic / 10**6:.3f} withheld). "
        + ("A coin moved on Base Sepolia." if total_settled > 0 else "No coin moved (all withheld).")
    )


if __name__ == "__main__":
    asyncio.run(_main())
