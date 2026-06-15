"""LIVE cross-owner smoke — run one full market job that recruits an agent the
market DOES NOT OWN, gated by a real mutual-contact handshake over live Band.

This is the on-network end-to-end counterpart to `tests/test_cross_owner.py` (which
proves the same flow OFFLINE on FakeBandClients). It extends
`spikes/discovery_recruiting_smoke.py` one beat further: besides the market's
same-owner specialists, it brings in a CROSS-OWNER tax bot (a second Band account) and
proves the consent gate — the bot is invisible to discovery until BOTH sides add each
other, after which it is discovered, bids, is hired, and recruited into the work room.

The handshake (inverse auto-accept):
  1. the owner2 tax bot adds the MARKET by handle (its half) — pending;
  2. `run_market_job(..., cross_owner_handles=[tax_handle])` has the market add the
     tax bot (its half), which finds the pending inverse request and auto-approves;
  3. the now-established contact shows up in `discover_pool` (peers ∪ contacts).

It is NOT run by the test suite — the orchestrator runs it by hand when live Band keys
+ a probe model + a SECOND Band account are configured:

    python3 spikes/cross_owner_smoke.py

It reads from `.env`: `BAND_MARKET_KEY`, per-specialist `BAND_SPECIALIST_<NAME>_KEY`,
`OPENAI_API_KEY` (+ optional `OPENAI_PROBE_MODEL`, `JOB_BUDGET_USD`), and the cross-owner
pieces `BAND_AGENT_OWNER2_KEY` + `BAND_OWNER2_TAX_HANDLE`. With the cross-owner pieces
missing it prints a one-line setup hint and exits cleanly — never crashes, never spends.
"""

from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import httpx
from dotenv import load_dotenv

from agent_exchange.band.consent import establish_contact
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

# A small but realistic ~8-clause MSA — enough surface for each specialist to probe,
# including a TAX clause so the cross-owner tax bot has something to bid on.
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
30-day cure period. Client may terminate for convenience on 60 days' notice.

5. Confidentiality & Data. Each party shall protect the other's Confidential \
Information for 3 years after disclosure. Vendor shall notify Client of any security \
breach within 72 hours.

6. Indemnification. Vendor shall indemnify Client against third-party claims that the \
deliverables infringe IP rights, including defense costs and settlements.

7. Warranties. Vendor warrants the services will be performed in a professional and \
workmanlike manner. EXCEPT AS STATED, THE SERVICES ARE PROVIDED "AS IS".

8. Governing Law. This Agreement is governed by the laws of the State of Delaware.
"""


async def _main() -> None:
    owner2_key = (os.getenv("BAND_AGENT_OWNER2_KEY") or "").strip()
    owner2_tax_handle = (os.getenv("BAND_OWNER2_TAX_HANDLE") or "").strip()
    if not owner2_key or not owner2_tax_handle:
        print(
            "Cross-owner smoke needs a SECOND Band account: set BAND_AGENT_OWNER2_KEY "
            "(the other org's tax bot key) and BAND_OWNER2_TAX_HANDLE (its handle, e.g. "
            "'other-org/tax-clause-bot') in .env, then re-run. Exiting without spending."
        )
        return

    market_key = (os.getenv("BAND_MARKET_KEY") or "").strip()
    if not market_key:
        # Fall back to any same-owner specialist key so the market still has identity.
        keys = specialist_band_keys()
        market_key = next(iter(keys.values()), "")
    if not market_key:
        print(
            "No market key — set BAND_MARKET_KEY (or a BAND_SPECIALIST_<NAME>_KEY) in "
            ".env so the market has a Band identity. Exiting without spending."
        )
        return

    market = make_http_band_client(market_key)
    owner2_tax = make_http_band_client(owner2_key)

    # Same-owner specialists (optional — the cross-owner bot is the star here).
    spec_keys = specialist_band_keys()
    agents = []
    if spec_keys:
        agents = build_bidding_agents(
            SPECIALISTS,
            spec_keys,
            probe_backend=make_backend("openai", os.getenv("OPENAI_PROBE_MODEL", "gpt-4.1-mini")),
            reputation=JsonReputationStore("data/reputation.json"),
            band_factory=make_http_band_client,
        )

    # Wire the cross-owner tax bot as a running BIDDING agent so it can actually bid +
    # be recruited (its specialty key 'tax' is what hiring/recruiting routes on).
    cross_agents = build_bidding_agents(
        [("tax", "tax responsibility, gross-up, and withholding", "")],
        {"tax": owner2_key},
        probe_backend=make_backend("openai", os.getenv("OPENAI_PROBE_MODEL", "gpt-4.1-mini")),
        reputation=JsonReputationStore("data/reputation.json"),
        band_factory=make_http_band_client,
    )
    agents = list(agents) + list(cross_agents)

    print("\nCross-owner consent handshake (inverse auto-accept):")

    # Resolve the market's own handle so the owner2 bot can add it (its half).
    try:
        market_me = await market.me()
    except httpx.HTTPStatusError as exc:
        print(f"  Band /me failed for the market: {exc.response.status_code} — {exc.response.text}")
        return
    market_handle = market_me.get("handle") or ""
    print(f"  market identity: {market_me.get('name')}  {market_handle}  ({market_me.get('id')})")

    # 1. The owner2 tax bot expresses willingness toward the market (its half).
    try:
        bot_half = await establish_contact(owner2_tax, market_handle)
    except httpx.HTTPStatusError as exc:
        print(f"  owner2 → market add_contact failed: {exc.response.status_code} — {exc.response.text}")
        return
    print(f"  owner2 tax bot adds market   → {bot_half.get('status')}")
    print("  market's half is driven inside run_market_job via cross_owner_handles "
          f"(adds '{owner2_tax_handle}') → inverse auto-accept.")

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
            job,
            market,
            agents,
            policy,
            work_room_title="Acme MSA — hired team (incl. cross-owner)",
            cross_owner_handles=[owner2_tax_handle],
        )
    except httpx.HTTPStatusError as exc:
        req = exc.request
        print(f"\nBand API error during market job: {exc.response.status_code} on "
              f"{req.method} {req.url} — {exc.response.text}")
        return

    decision = result.decision
    team = result.team

    print(f"\nJob '{job.title}' — full cross-owner lifecycle (handshake → discover → bid → hire → recruit)\n")

    # 1. discovered pool (should now include the cross-owner tax bot) -----------
    print(f"DISCOVERED POOL ({len(result.pool)}):")
    if result.pool:
        for ident in result.pool:
            cross = "  ← CROSS-OWNER" if ident.handle == owner2_tax_handle else ""
            print(f"  • {ident.name:<16} {ident.handle}  ({ident.id}){cross}")
    else:
        print("  (none — discovery returned an empty pool; fell back to configured agents)")
    cross_in_pool = any(ident.handle == owner2_tax_handle for ident in result.pool)
    print(f"  cross-owner tax bot in pool: {cross_in_pool}")

    # 2. bids ------------------------------------------------------------------
    print(f"\nBIDS in room {result.bidding_room_id} ({len(result.bids)}):")
    if result.bids:
        for b in sorted(result.bids, key=lambda x: x.worker):
            price_usd = b.price_atomic / 10**6
            print(
                f"  • {b.worker:<16} ${price_usd:>8.4f}  "
                f"relevance={b.relevance_confidence:.2f}  reputation={b.reputation.success_rate:.2f}"
            )
    else:
        print("  (no bids received — nothing to hire)")

    # 3. hired -----------------------------------------------------------------
    authorized_usd = decision.budget_atomic / 10**6
    total_usd = decision.total_price_atomic / 10**6
    print(f"\nHIRED ({decision.n_hired}) — strategy {decision.strategy}, budget ${authorized_usd:.4f}:")
    if decision.hired:
        for h in sorted(decision.hired, key=lambda x: x.worker):
            price_usd = h.price_atomic / 10**6
            print(f"  • {h.worker:<16} ${price_usd:>8.4f}  value={h.value:.3f}  relevance={h.relevance:.2f}")
    else:
        print("  (none)")
    if decision.declined:
        print(f"  declined: {', '.join(sorted(decision.declined))}")
    print(f"  total ${total_usd:.4f} of ${authorized_usd:.4f}  (over-budget fallback: {decision.over_budget})")

    # 4. recruited team into a work room ---------------------------------------
    print(f"\nRECRUITED TEAM → work room {team.work_room_id} ({team.n_recruited}):")
    if team.recruited:
        for name in team.recruited:
            cross = "  ← CROSS-OWNER" if name == "tax" else ""
            print(f"  • {name}{cross}")
    else:
        print("  (none recruited)")
    if team.skipped:
        print(f"  skipped (hired but no known identity): {', '.join(team.skipped)}")

    print(
        f"\nRESULT: cross-owner tax bot — discovered={cross_in_pool}, "
        f"recruited={'tax' in team.recruited}."
    )


if __name__ == "__main__":
    asyncio.run(_main())
