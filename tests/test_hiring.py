"""Hiring-layer tests — Thompson scoring, coverage-within-budget selection, the
end-to-end `HiringPolicy`, and @mention-routed hire notifications, proven OFFLINE.

The hiring stage consumes the bids `run_bidding` produced and picks a team:

  1. `thompson_value` draws a per-bid quality SAMPLE from the worker's reputation
     posterior scaled by the bid's relevance — so high-rep/high-relevance bids
     rank higher in expectation while a fresh (no-history) worker keeps exploration
     variance (it isn't deterministically frozen out).
  2. `score_bids` turns a list of `Bid`s into `ScoredBid`s using one seeded RNG.
  3. `CoverageWithinBudget` greedily hires the best bids that fit the budget, with a
     soft-cap fallback (if NOTHING fits, hire the single best so a demo job always
     produces a team, flagging `over_budget=True`).
  4. `HiringPolicy(strategy, seed=...)` wires a seeded RNG through `score_bids` +
     the strategy into a `HiringDecision`.
  5. `post_hiring` announces each hire back into the Band room, @mentioning the hired
     worker so Band's routing delivers a "you're hired" message to exactly that agent.

Runnable two ways:
  - `python3 tests/test_hiring.py`   (no pytest needed — the __main__ runner)
  - `pytest`                          (plain sync test_* functions; async ones asyncio.run)
"""

from __future__ import annotations

import asyncio
import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from agent_exchange.band.client import BandWorld, FakeBandClient
from agent_exchange.market.hiring import HiringPolicy, hire_and_notify, post_hiring
from agent_exchange.market.hiring_types import Hire, HiringDecision, ScoredBid
from agent_exchange.market.schema import Bid, Job, ReputationRecord
from agent_exchange.market.selection import (
    CoverageWithinBudget,
    KnapsackStrategy,
    score_bids,
    thompson_value,
)
from agent_exchange.metrics import usdc

# 1 USDC == 10**6 atomic; 1 cent == 10**4 atomic (matches bidding.py).
_ATOMIC_PER_CENT = 10**4


def _bid(worker: str, *, price_cents: int, relevance: float, rep: ReputationRecord) -> Bid:
    """A `Bid` with the price expressed in whole cents (atomic = cents * 10**4)."""
    return Bid(
        worker=worker,
        job_id="acme-1",
        price_atomic=price_cents * _ATOMIC_PER_CENT,
        relevance_confidence=relevance,
        reputation=rep,
    )


# ── thompson_value / score_bids: determinism + the expectation properties ──


def test_thompson_value_is_deterministic_for_the_same_seeded_rng():
    rep = ReputationRecord(worker="liability", n_jobs=20, success_rate=0.9)
    a = thompson_value(rep, 0.8, random.Random(7))
    b = thompson_value(rep, 0.8, random.Random(7))
    assert a == b  # same seed → identical sample


def test_score_bids_is_deterministic_for_the_same_seeded_rng():
    rep = ReputationRecord(worker="liability", n_jobs=20, success_rate=0.9)
    bids = [
        _bid("liability", price_cents=200, relevance=0.9, rep=rep),
        _bid("ip", price_cents=150, relevance=0.6, rep=ReputationRecord(worker="ip")),
    ]
    first = score_bids(list(bids), random.Random(7))
    second = score_bids(list(bids), random.Random(7))
    assert [s.value for s in first] == [s.value for s in second]
    # ScoredBid wraps the original bid unchanged.
    assert all(isinstance(s, ScoredBid) for s in first)
    assert [s.bid.worker for s in first] == ["liability", "ip"]


def test_high_rep_outscores_low_rep_in_expectation_over_many_seeds():
    # Same relevance (0.9) and same job count (20): the only difference is the
    # success rate, so over many seeds the high-success worker should average higher.
    high = ReputationRecord(worker="hi", n_jobs=20, success_rate=0.95)
    low = ReputationRecord(worker="lo", n_jobs=20, success_rate=0.2)

    hi_total = sum(thompson_value(high, 0.9, random.Random(s)) for s in range(400))
    lo_total = sum(thompson_value(low, 0.9, random.Random(s)) for s in range(400))
    assert hi_total > lo_total  # exploitation: better track record wins on average


def test_fresh_worker_has_exploration_variance_across_seeds():
    # A never-seen worker (n_jobs=0, success_rate=0.5) must NOT collapse to a single
    # frozen value — its Thompson samples vary across seeds (that variance IS the
    # exploration that lets an unproven worker still win sometimes).
    fresh = ReputationRecord(worker="new", n_jobs=0, success_rate=0.5)
    samples = [thompson_value(fresh, 0.9, random.Random(s)) for s in range(50)]
    assert len(set(samples)) > 1, "a fresh worker's samples must not all be equal"


# ── CoverageWithinBudget: greedy fit + soft-cap fallback ──


def _three_scored_bids():
    """Three bids with distinct prices/quality, hand-scored so selection is exact.

    Scored by hand (NOT via the RNG) so the budget arithmetic in these tests is
    deterministic and independent of the Thompson sampler. Best→worst by value:
    liability(2.0) > ip(1.5) > tax(0.4); prices 200/150/300 cents.
    """
    rep = ReputationRecord(worker="x", n_jobs=20, success_rate=0.9)
    return [
        ScoredBid(_bid("liability", price_cents=200, relevance=0.9, rep=rep), value=2.0),
        ScoredBid(_bid("ip", price_cents=150, relevance=0.8, rep=rep), value=1.5),
        ScoredBid(_bid("tax", price_cents=300, relevance=0.4, rep=rep), value=0.4),
    ]


def test_coverage_within_budget_hires_the_best_that_fit():
    scored = _three_scored_bids()
    # Budget admits the two best (200 + 150 = 350 cents) but not the third (+300).
    budget = (200 + 150) * _ATOMIC_PER_CENT
    hired, declined, over_budget = CoverageWithinBudget().select(scored, budget)
    assert {h.worker for h in hired} == {"liability", "ip"}
    assert len(hired) == 2
    assert declined == ["tax"]
    assert over_budget is False
    # Hired set stays within budget.
    assert sum(h.price_atomic for h in hired) <= budget


def test_coverage_within_budget_soft_cap_fallback_hires_exactly_the_best():
    scored = _three_scored_bids()
    # Budget below EVERY bid's price → nothing fits → fallback hires the single best.
    budget = 1  # 1 atomic unit; cheaper than the cheapest 150-cent bid
    hired, declined, over_budget = CoverageWithinBudget().select(scored, budget)
    assert len(hired) == 1
    assert hired[0].worker == "liability"        # the best by value
    assert over_budget is True
    assert sorted(declined) == ["ip", "tax"]


def test_knapsack_strategy_is_not_implemented_yet():
    scored = _three_scored_bids()
    try:
        KnapsackStrategy().select(scored, 10**9)
    except NotImplementedError:
        return
    raise AssertionError("KnapsackStrategy().select should raise NotImplementedError")


# ── HiringPolicy end-to-end: bids → HiringDecision ──


def _three_bids():
    """Three real `Bid`s: liability + ip are strong (high rep, high relevance), tax weak."""
    strong = ReputationRecord(worker="x", n_jobs=20, success_rate=0.95)
    weak = ReputationRecord(worker="y", n_jobs=20, success_rate=0.2)
    return [
        _bid("liability", price_cents=200, relevance=0.9, rep=strong),
        _bid("ip", price_cents=150, relevance=0.85, rep=strong),
        _bid("tax", price_cents=120, relevance=0.2, rep=weak),
    ]


def _job(budget_cents: int) -> Job:
    return Job(
        job_id="acme-1",
        contract="MASTER SERVICES AGREEMENT ...",
        budget_atomic=budget_cents * _ATOMIC_PER_CENT,
        title="Audit Acme MSA",
    )


def test_hiring_policy_hires_two_within_budget():
    bids = _three_bids()
    # Budget admits the two strongest (200 + 150 = 350 cents) but not all three.
    job = _job(360)
    decision = HiringPolicy(CoverageWithinBudget(), seed=1).select(job, bids)
    assert isinstance(decision, HiringDecision)
    assert decision.n_hired == 2
    assert len(decision.declined) == 1
    # total_price equals the sum of the hired prices, and stays within budget.
    assert decision.total_price_atomic == sum(h.price_atomic for h in decision.hired)
    assert decision.total_price_atomic <= job.budget_atomic
    assert decision.over_budget is False
    assert decision.strategy == "coverage_within_budget"
    assert "tax" in decision.declined  # the weak, low-relevance bid is the odd one out


def test_hiring_policy_over_budget_job_falls_back_to_one_hire():
    bids = _three_bids()
    # Budget below the cheapest bid (120 cents) → soft-cap fallback fires.
    job = _job(1)
    decision = HiringPolicy(CoverageWithinBudget(), seed=1).select(job, bids)
    assert decision.over_budget is True
    assert decision.n_hired == 1
    assert len(decision.declined) == 2


def test_hiring_policy_empty_bids_yields_an_empty_decision():
    job = _job(360)
    decision = HiringPolicy(CoverageWithinBudget(), seed=1).select(job, [])
    assert decision.n_hired == 0
    assert decision.declined == ()
    assert decision.total_price_atomic == 0
    assert decision.over_budget is False


# ── post_hiring: @mention routing delivers a "you're hired" message per hire ──


async def _mention_for(client: FakeBandClient) -> dict:
    me = await client.me()
    return {"id": me["id"], "handle": me["handle"], "name": me["name"]}


async def _run_post_hiring():
    world = BandWorld()
    market = FakeBandClient("m", "@x/market", "market", world)
    liability = FakeBandClient("liability", "@x/liability", "liability", world)
    ip = FakeBandClient("ip", "@x/ip", "ip", world)

    room_id = await market.create_room("Audit Acme MSA")
    await market.add_participant(room_id, "liability")
    await market.add_participant(room_id, "ip")

    mention_for = {
        "liability": await _mention_for(liability),
        "ip": await _mention_for(ip),
    }

    decision = HiringDecision(
        hired=(
            Hire(worker="liability", price_atomic=200 * _ATOMIC_PER_CENT, value=2.0, relevance=0.9),
            Hire(worker="ip", price_atomic=150 * _ATOMIC_PER_CENT, value=1.5, relevance=0.85),
        ),
        declined=("tax",),
        total_price_atomic=350 * _ATOMIC_PER_CENT,
        budget_atomic=usdc(0.05),
        over_budget=False,
        strategy="coverage_within_budget",
    )

    await post_hiring(decision, market, room_id, mention_for)

    # Each HIRED worker received a message (the @mention routed it to them).
    liability_msg = await liability.get_next_message(room_id)
    ip_msg = await ip.get_next_message(room_id)
    return liability_msg, ip_msg


def test_post_hiring_notifies_each_hired_worker_via_mention_routing():
    liability_msg, ip_msg = asyncio.run(_run_post_hiring())
    assert liability_msg is not None, "the hired 'liability' worker got no message"
    assert ip_msg is not None, "the hired 'ip' worker got no message"
    # The delivered message is a hire notification.
    assert "hired" in liability_msg["content"].lower()
    assert "hired" in ip_msg["content"].lower()
    # It was sent by the market, not self-posted.
    assert liability_msg["sender_id"] == "m"
    assert ip_msg["sender_id"] == "m"


# ── hire_and_notify: select + announce in one call ──


async def _run_hire_and_notify():
    world = BandWorld()
    market = FakeBandClient("m", "@x/market", "market", world)
    liability = FakeBandClient("liability", "@x/liability", "liability", world)
    ip = FakeBandClient("ip", "@x/ip", "ip", world)
    tax = FakeBandClient("tax", "@x/tax", "tax", world)

    room_id = await market.create_room("Audit Acme MSA")
    for cid in ("liability", "ip", "tax"):
        await market.add_participant(room_id, cid)

    mention_for = {
        "liability": await _mention_for(liability),
        "ip": await _mention_for(ip),
        "tax": await _mention_for(tax),
    }

    policy = HiringPolicy(CoverageWithinBudget(), seed=1)
    decision = await hire_and_notify(_job(360), _three_bids(), market, room_id, mention_for, policy)

    liability_msg = await liability.get_next_message(room_id)
    tax_msg = await tax.get_next_message(room_id)
    return decision, liability_msg, tax_msg


def test_hire_and_notify_selects_then_announces_only_to_hired_workers():
    decision, liability_msg, tax_msg = asyncio.run(_run_hire_and_notify())
    assert decision.n_hired == 2
    assert "tax" in decision.declined
    # the hired worker is notified...
    assert liability_msg is not None
    assert "hired" in liability_msg["content"].lower()
    # ...the declined worker is NOT notified (no hire message routed to it).
    assert tax_msg is None


def _run_all():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"  ✓ {fn.__name__}")
    print(f"\n{len(fns)} passed")


if __name__ == "__main__":
    _run_all()
