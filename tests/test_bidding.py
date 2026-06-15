"""Bidding-layer tests — the full post→probe→bid flow, proven OFFLINE.

`run_bidding` posts a `Job` to a market Band room, each `BiddingAgent` runs a cheap
`relevance_probe` over the contract preview, and the ones that choose to bid emit a
`Bid` (price + relevance + a reputation snapshot). We drive it with ZERO network: one
shared `BandWorld`, a market `FakeBandClient`, and per-specialist `FakeBandClient`s,
plus crafted `MockBackend` probe backends so each agent's bid/decline is deterministic.

Runnable two ways:
  - `python3 tests/test_bidding.py`   (no pytest needed — the __main__ runner)
  - `pytest`                          (plain sync test_* functions; each asyncio.runs)

The crafted scenario: liability + ip probe `{"bid": true, "relevance": 0.9,
"price_cents": 200}` (they bid), tax probes `{"bid": false, ...}` (declines), and a
4th agent whose probe backend RAISES (fail-soft: no bid, no crash). Result: exactly
two bids, deterministically ordered by worker, each at 200 cents == 200*10**4 atomic.
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
from agent_exchange.core.backend import ModelBackend
from agent_exchange.core.types import CompletionResult
from agent_exchange.market.bidding import BiddingAgent, relevance_probe, run_bidding
from agent_exchange.market.reputation import JsonReputationStore
from agent_exchange.market.schema import Bid, ReputationRecord


# A short MSA preview is enough for the (mocked) probe; nothing reads the real text.
CONTRACT = (
    "MASTER SERVICES AGREEMENT\n"
    "1. Liability. Vendor's aggregate liability is capped at fees paid in the prior 12 months.\n"
    "2. Intellectual Property. All work product is assigned to Client.\n"
    "3. Taxes. Each party bears its own income taxes.\n"
)

_BID_REPLY = json.dumps({"bid": True, "relevance": 0.9, "price_cents": 200})
_DECLINE_REPLY = json.dumps({"bid": False, "relevance": 0.0, "price_cents": 0})


class _RaisingBackend(ModelBackend):
    """A probe backend whose `complete` always raises — proves run_bidding is fail-soft."""

    async def complete(self, messages, *, temperature: float = 0.0, max_tokens=None) -> CompletionResult:
        raise RuntimeError("probe backend exploded")


def _make_job():
    # usdc(0.05) authorized; the Job dataclass is frozen + slots (see market/schema.py).
    from agent_exchange.metrics import usdc

    from agent_exchange.market.schema import Job

    return Job(
        job_id="acme-1",
        contract=CONTRACT,
        budget_atomic=usdc(0.05),
        title="Audit Acme MSA",
    )


def _run_full_flow(*, with_raiser: bool):
    """Build the shared world + agents and run one bidding round. Returns (room_id, bids)."""
    world = BandWorld()
    market = FakeBandClient("market", "@x/market", "market", world)

    with tempfile.TemporaryDirectory() as d:
        reputation = JsonReputationStore(os.path.join(d, "rep.json"))

        specs = [
            ("liability", "liability caps and disclaimers", _BID_REPLY, MockBackend),
            ("ip", "IP ownership, licenses, assignment", _BID_REPLY, MockBackend),
            ("tax", "tax responsibility and gross-up", _DECLINE_REPLY, MockBackend),
        ]
        agents = []
        for name, area, reply, _ in specs:
            band = FakeBandClient(name, f"@x/{name}", name, world)
            agents.append(
                BiddingAgent(
                    specialty=name,
                    area=area,
                    band=band,
                    probe_backend=MockBackend(reply=reply),
                    reputation=reputation,
                )
            )

        if with_raiser:
            band = FakeBandClient("boom", "@x/boom", "boom", world)
            agents.append(
                BiddingAgent(
                    specialty="boom",
                    area="a specialty whose probe raises",
                    band=band,
                    probe_backend=_RaisingBackend(),
                    reputation=reputation,
                )
            )

        return asyncio.run(run_bidding(_make_job(), market, agents))


# ── the happy path: two bidders, one decliner ──

def test_run_bidding_returns_two_bids_for_the_two_bidders():
    room_id, bids = _run_full_flow(with_raiser=False)
    assert isinstance(room_id, str) and room_id
    assert len(bids) == 2
    workers = [b.worker for b in bids]
    assert workers == ["ip", "liability"]            # deterministic: sorted by worker
    assert "tax" not in workers                        # the decliner produced no bid


def test_each_bid_carries_price_relevance_and_a_reputation_snapshot():
    _room_id, bids = _run_full_flow(with_raiser=False)
    for b in bids:
        assert isinstance(b, Bid)
        assert b.job_id == "acme-1"
        # 200 cents → atomic USDC: cents * 10**4  (1 USDC == 10**6, 1 cent == 10**4)
        assert b.price_atomic == 200 * 10**4
        assert b.relevance_confidence == 0.9
        assert isinstance(b.reputation, ReputationRecord)
        # unseen workers → neutral prior snapshot
        assert b.reputation.success_rate == 0.5


# ── fail-soft: a probe backend that raises yields no bid, no crash ──

def test_a_raising_probe_backend_yields_no_bid_and_does_not_crash():
    room_id, bids = _run_full_flow(with_raiser=True)
    assert isinstance(room_id, str) and room_id
    # still exactly the two genuine bidders; the exploding agent simply abstained
    workers = sorted(b.worker for b in bids)
    assert workers == ["ip", "liability"]
    assert "boom" not in workers


# ── relevance_probe parsing: valid JSON, fenced ```json, and garbage ──

def test_relevance_probe_parses_valid_json():
    backend = MockBackend(reply=_BID_REPLY)
    out = asyncio.run(relevance_probe("liability caps", CONTRACT[:1200], backend))
    assert out["bid"] is True
    assert out["relevance"] == 0.9
    assert out["price_cents"] == 200


def test_relevance_probe_parses_fenced_json_block():
    fenced = "```json\n" + json.dumps({"bid": True, "relevance": 0.7, "price_cents": 150}) + "\n```"
    backend = MockBackend(reply=fenced)
    out = asyncio.run(relevance_probe("ip licenses", CONTRACT[:1200], backend))
    assert out["bid"] is True
    assert out["relevance"] == 0.7
    assert out["price_cents"] == 150


def test_relevance_probe_fails_soft_on_garbage():
    backend = MockBackend(reply="not json at all — sorry, I can't help with that")
    out = asyncio.run(relevance_probe("tax gross-up", CONTRACT[:1200], backend))
    # fail-soft: garbage → a no-bid verdict, never a raise
    assert out["bid"] is False


def _run_all():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"  ✓ {fn.__name__}")
    print(f"\n{len(fns)} passed")


if __name__ == "__main__":
    _run_all()
