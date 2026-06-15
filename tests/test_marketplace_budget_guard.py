"""Marketplace-level budget guard wire test.

Verifies that an over-budget job is declined at the `run_market_job` call site —
i.e. the guard is actually wired, not just built and ignored.  Uses the same
offline Fake infrastructure as `test_cross_owner.py` so no network or spend.

Strategy: set `budget_atomic=1` (one micro-USDC, effectively $0.000001) with a
realistic contract so `budget_guard_for_job` projects a cost well above that cap.
The guard should block, `decision.over_budget` should be True,
`decision.budget_block_reason` should be set, and no work room should be created
(team.work_room_id == "").
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from agent_exchange.band.client import BandWorld, FakeBandClient
from agent_exchange.core import MockBackend
from agent_exchange.market.bidding import BiddingAgent
from agent_exchange.market.hiring import HiringPolicy
from agent_exchange.market.marketplace import run_market_job
from agent_exchange.market.reputation import JsonReputationStore
from agent_exchange.market.schema import Job
from agent_exchange.market.selection import CoverageWithinBudget

# A realistic contract — long enough that estimate_cost returns a non-trivial value
# for any known model, ensuring the guard projection exceeds a $0.000001 cap.
_CONTRACT = (
    "MASTER SERVICES AGREEMENT\n"
    "1. Liability. Vendor's aggregate liability under this Agreement is capped at the "
    "fees paid by Client in the twelve (12) months preceding the claim.\n"
    "2. Taxes. Fees are stated exclusive of tax. Client bears all sales, use, and "
    "VAT/GST. Each party is responsible for its own income and franchise taxes.\n"
    "3. Termination. Either party may terminate for cause on 30 days written notice.\n"
    "4. Confidentiality. Each party shall protect the other's Confidential Information "
    "for 3 years after disclosure.\n"
)

_BID_REPLY = json.dumps({"bid": True, "relevance": 0.9, "price_cents": 200})


def _run_over_budget_job():
    """Run a job whose budget_atomic=1 (≈ $0.000001) through the full marketplace."""
    world = BandWorld()
    market = FakeBandClient("m-market", "@self/market", "market", world, owner="self")
    liability = FakeBandClient("s-liability", "@self/liability", "liability", world, owner="self")

    with tempfile.TemporaryDirectory() as d:
        reputation = JsonReputationStore(os.path.join(d, "rep.json"))
        agents = [
            BiddingAgent(
                specialty="liability",
                area="liability caps",
                band=liability,
                probe_backend=MockBackend(reply=_BID_REPLY),
                reputation=reputation,
            ),
        ]
        job = Job(
            job_id="tiny-budget-1",
            contract=_CONTRACT,
            budget_atomic=1,          # $0.000001 — below any realistic token cost
            title="Tiny Budget Audit",
        )
        policy = HiringPolicy(CoverageWithinBudget(), seed=1)
        return asyncio.run(
            run_market_job(
                job,
                market,
                agents,
                policy,
                # Use a real known model so estimate_cost returns a positive number.
                worker_model="claude-3-5-haiku",
                verifier_model="claude-3-5-haiku",
            )
        )


def test_over_budget_job_is_declined_at_marketplace_level():
    """An over-budget job is declined by the budget guard wired inside run_market_job.

    The decision must carry over_budget=True and a budget_block_reason; the team
    must have no work_room_id (guard blocks before recruit_team is called).
    """
    result = _run_over_budget_job()

    assert result.decision.over_budget is True, (
        "expected over_budget=True from the budget guard"
    )
    assert result.decision.budget_block_reason is not None, (
        "expected budget_block_reason to be set when the guard fires"
    )
    assert result.decision.n_hired == 0, (
        "expected no hires when the budget guard blocks"
    )
    # No work room was created — the guard fired before recruit_team.
    assert result.team.work_room_id == "", (
        "expected empty work_room_id when the job is guard-blocked"
    )
    assert result.team.recruited == (), (
        "expected no recruited workers on a guard-blocked job"
    )


if __name__ == "__main__":
    test_over_budget_job_is_declined_at_marketplace_level()
    print("ok  test_over_budget_job_is_declined_at_marketplace_level")
