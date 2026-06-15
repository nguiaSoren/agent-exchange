"""LIVE discovery → recruiting smoke — run one full market job through real Band:
DISCOVER the same-owner agent pool, run bidding among them, HIRE a team, and RECRUIT
the hired into a dedicated work room.

This is the on-network end-to-end counterpart to `tests/test_discovery.py` +
`tests/test_recruiting.py` (which prove discovery and recruiting OFFLINE on
FakeBandClients). It extends `spikes/hiring_smoke.py` one box further: instead of a
hardcoded roster it lets the market DISCOVER its pool via Band peers, then runs the
whole lifecycle through `run_market_job` (discover → bid → hire → recruit into a work
room).

It is NOT run by the test suite — the orchestrator runs it by hand when live Band keys
+ a probe model are configured:

    python3 spikes/discovery_recruiting_smoke.py

It reads keys from `.env`: per-specialist `BAND_SPECIALIST_<NAME>_KEY`, a
`BAND_MARKET_KEY`, an `OPENAI_API_KEY` for the relevance probe, and optionally
`OPENAI_PROBE_MODEL` (defaults to gpt-4.1-mini) and `JOB_BUDGET_USD`. With no
specialist keys it prints a one-line registration hint and exits cleanly — never
crashes, never spends.
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
from agent_exchange.market.bidding import build_bidding_agents
from agent_exchange.market.hiring import HiringPolicy
from agent_exchange.market.marketplace import run_market_job
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

    policy = HiringPolicy(CoverageWithinBudget(), seed=1)

    try:
        result = await run_market_job(
            job, market, agents, policy, work_room_title="Acme MSA — hired team"
        )
    except httpx.HTTPStatusError as exc:
        print(f"Band API error during market job: {exc.response.status_code} — {exc.response.text}")
        return

    decision = result.decision
    team = result.team

    print(f"\nJob '{job.title}' — full market lifecycle (discover → bid → hire → recruit)\n")

    # 1. discovered pool ----------------------------------------------------
    print(f"DISCOVERED POOL ({len(result.pool)}):")
    if result.pool:
        for ident in result.pool:
            print(f"  • {ident.name:<14} {ident.handle}  ({ident.id})")
    else:
        print("  (none — discovery returned an empty pool; fell back to configured agents)")

    # 2. bids ---------------------------------------------------------------
    print(f"\nBIDS in room {result.bidding_room_id} ({len(result.bids)}):")
    if result.bids:
        for b in sorted(result.bids, key=lambda x: x.worker):
            price_usd = b.price_atomic / 10**6
            print(
                f"  • {b.worker:<14} ${price_usd:>8.4f}  "
                f"relevance={b.relevance_confidence:.2f}  reputation={b.reputation.success_rate:.2f}"
            )
    else:
        print("  (no bids received — nothing to hire)")

    # 3. hired --------------------------------------------------------------
    authorized_usd = decision.budget_atomic / 10**6
    total_usd = decision.total_price_atomic / 10**6
    print(f"\nHIRED ({decision.n_hired}) — strategy {decision.strategy}, budget ${authorized_usd:.4f}:")
    if decision.hired:
        for h in sorted(decision.hired, key=lambda x: x.worker):
            price_usd = h.price_atomic / 10**6
            print(f"  • {h.worker:<14} ${price_usd:>8.4f}  value={h.value:.3f}  relevance={h.relevance:.2f}")
    else:
        print("  (none)")
    if decision.declined:
        print(f"  declined: {', '.join(sorted(decision.declined))}")
    print(f"  total ${total_usd:.4f} of ${authorized_usd:.4f}  (over-budget fallback: {decision.over_budget})")

    # 4. recruited team into a work room ------------------------------------
    print(f"\nRECRUITED TEAM → work room {team.work_room_id} ({team.n_recruited}):")
    if team.recruited:
        for name in team.recruited:
            print(f"  • {name}")
    else:
        print("  (none recruited)")
    if team.skipped:
        print(f"  skipped (hired but no known identity): {', '.join(team.skipped)}")


if __name__ == "__main__":
    asyncio.run(_main())
