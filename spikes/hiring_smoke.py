"""LIVE hiring smoke — run one real bidding round through Band, then HIRE a team and
notify the hired workers in-room.

This is the on-network end-to-end counterpart to `tests/test_hiring.py` (which proves
the same selection + notification flow OFFLINE on FakeBandClients). It extends
`spikes/bidding_smoke.py` one box further: after `run_bidding` collects real bids, a
`HiringPolicy(CoverageWithinBudget())` picks the team that fits the budget and
`hire_and_notify` announces each hire back into the room via @mention routing.

It is NOT run by the test suite — the orchestrator runs it by hand when live Band keys
+ a probe model are configured:

    python3 spikes/hiring_smoke.py

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
from agent_exchange.market.hiring import HiringPolicy, hire_and_notify
from agent_exchange.market.reputation import JsonReputationStore
from agent_exchange.market.schema import Job
from agent_exchange.market.selection import CoverageWithinBudget
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

    # Budget is a demo knob: the default ($0.05) is testnet-x402 scale and forces the
    # soft-cap fallback against real-world-priced bids; set JOB_BUDGET_USD higher (e.g.
    # 200) to exercise the clean within-budget greedy branch live.
    budget_usd = float(os.getenv("JOB_BUDGET_USD", "0.05"))
    job = Job(
        job_id="acme-1",
        contract=SAMPLE_MSA,
        budget_atomic=usdc(budget_usd),
        title="Audit Acme MSA",
    )

    try:
        room_id, bids = await run_bidding(job, market, agents)

        if not bids:
            print(f"\nJob '{job.title}' posted to room {room_id} — no bids received; nothing to hire.")
            return

        # Build mention_for from each bidding agent's live identity (the @mention dict
        # the hire notification routes on). Keyed by the worker/specialty id.
        mention_for: dict[str, dict] = {}
        for agent in agents:
            me = await agent.band.me()
            mention_for[agent.specialty] = {
                "id": me["id"],
                "handle": me.get("handle", ""),
                "name": me.get("name", agent.specialty),
            }

        policy = HiringPolicy(CoverageWithinBudget(), seed=1)
        decision = await hire_and_notify(job, bids, market, room_id, mention_for, policy)
    except httpx.HTTPStatusError as exc:
        print(f"Band API error during bidding/hiring: {exc.response.status_code} — {exc.response.text}")
        return

    budget_usd = decision.budget_atomic / 10**6
    total_usd = decision.total_price_atomic / 10**6

    print(f"\nJob '{job.title}' posted to room {room_id}")
    print(f"Authorized budget: ${budget_usd:.4f} USDC")
    print(f"Strategy: {decision.strategy}\n")

    if decision.hired:
        print(f"HIRED ({decision.n_hired}):")
        for h in sorted(decision.hired, key=lambda x: x.worker):
            price_usd = h.price_atomic / 10**6
            print(f"  • {h.worker:<14} ${price_usd:>8.4f}  value={h.value:.3f}  relevance={h.relevance:.2f}")
    else:
        print("HIRED: none")

    if decision.declined:
        print(f"\nDeclined: {', '.join(sorted(decision.declined))}")

    print(f"\nTotal hired: ${total_usd:.4f} of ${budget_usd:.4f} budget")
    print(f"Over budget (soft-cap fallback fired): {decision.over_budget}")


if __name__ == "__main__":
    asyncio.run(_main())
