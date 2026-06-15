"""LIVE bidding smoke — post one MSA job to the real Band market room and collect
real bids from the registered specialist agents.

This is the on-network counterpart to `tests/test_bidding.py` (which proves the same
flow OFFLINE on FakeBandClients). It is NOT run by the test suite — the orchestrator
runs it by hand when live Band keys + a probe model are configured:

    python3 spikes/bidding_smoke.py

It reads keys from `.env`: per-specialist `BAND_SPECIALIST_<NAME>_KEY`, a
`BAND_MARKET_KEY`, an `OPENAI_API_KEY` for the relevance probe, and optionally
`OPENAI_PROBE_MODEL` (defaults to gpt-4.1-mini). With no specialist keys it prints a
one-line registration hint and exits cleanly — never crashes, never spends.
"""

from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import httpx
from dotenv import load_dotenv

from agent_exchange.band.http_client import make_http_band_client, specialist_band_keys
from agent_exchange.core import make_backend
from agent_exchange.market.bidding import build_bidding_agents, run_bidding
from agent_exchange.market.reputation import JsonReputationStore
from agent_exchange.market.schema import Job
from agent_exchange.metrics import usdc
from agent_exchange.workers.specialist import SPECIALISTS

# Explicit path (load_dotenv() with no path can fail depending on cwd). Env is read
# lazily by make_backend at call time, so loading it after the imports is fine.
load_dotenv("/Users/soren/Desktop/BAND HACKATHON/agent-exchange/.env")

# A small but realistic ~8-clause MSA — enough surface for each specialist to probe.
SAMPLE_MSA = """\
MASTER SERVICES AGREEMENT

1. Liability. Vendor's aggregate liability under this Agreement is capped at the fees \
paid by Client in the twelve (12) months preceding the claim. This cap does not apply \
to breaches of confidentiality or indemnification obligations.

2. Intellectual Property. All work product, deliverables, and foreground IP created \
under this Agreement are assigned to Client upon creation. Vendor retains its \
pre-existing background IP and grants Client a non-exclusive license to use it.

3. Taxes. Fees are stated exclusive of tax. Client bears all sales, use, and VAT/GST. \
Each party is responsible for its own income and franchise taxes. Client shall gross \
up any withholding so Vendor receives the full invoiced amount.

4. Termination. Either party may terminate for cause on 30 days' written notice with a \
30-day cure period. Client may terminate for convenience on 60 days' notice. The \
initial term is 12 months and auto-renews for successive 12-month terms unless either \
party gives 30 days' notice of non-renewal.

5. Confidentiality & Data. Each party shall protect the other's Confidential \
Information for 3 years after disclosure. Vendor may not use Client data to train \
models. Vendor shall notify Client of any security breach within 72 hours.

6. Indemnification. Vendor shall indemnify Client against third-party claims that the \
deliverables infringe IP rights, including defense costs and settlements. This \
indemnity is expressly excluded from the liability cap in Clause 1.

7. Warranties. Vendor warrants the services will be performed in a professional and \
workmanlike manner. EXCEPT AS STATED, THE SERVICES ARE PROVIDED "AS IS".

8. Governing Law. This Agreement is governed by the laws of the State of Delaware.
"""


async def _main() -> None:
    keys = specialist_band_keys()
    if not keys:
        print(
            "Register specialist agents at app.band.ai and add "
            "BAND_SPECIALIST_<NAME>_KEY to .env (you have a market key + can reuse for now)."
        )
        return

    agents = build_bidding_agents(
        SPECIALISTS,
        keys,
        probe_backend=make_backend("openai", os.getenv("OPENAI_PROBE_MODEL", "gpt-4.1-mini")),
        reputation=JsonReputationStore("data/reputation.json"),
        band_factory=make_http_band_client,
    )

    market = make_http_band_client(os.getenv("BAND_MARKET_KEY") or next(iter(keys.values())))

    job = Job(
        job_id="acme-1",
        contract=SAMPLE_MSA,
        budget_atomic=usdc(0.05),
        title="Audit Acme MSA",
    )

    try:
        room_id, bids = await run_bidding(job, market, agents)
    except httpx.HTTPStatusError as exc:
        print(f"Band API error during bidding: {exc.response.status_code} — {exc.response.text}")
        return

    print(f"\nJob '{job.title}' posted to room {room_id}")
    print(f"Authorized budget: ${job.budget_atomic / 10**6:.4f} USDC\n")

    bid_workers = {b.worker for b in bids}
    if bids:
        print(f"{len(bids)} bid(s) received:")
        for b in sorted(bids, key=lambda x: x.worker):
            price_usd = b.price_atomic / 10**6
            rep = b.reputation.success_rate
            print(
                f"  • {b.worker:<14} ${price_usd:>8.4f}  "
                f"relevance={b.relevance_confidence:.2f}  reputation={rep:.2f}"
            )
    else:
        print("No bids received.")

    declined = sorted(name for name, _area, _prompt in SPECIALISTS if name not in bid_workers)
    if declined:
        print(f"\nDeclined / no bid: {', '.join(declined)}")


if __name__ == "__main__":
    asyncio.run(_main())
