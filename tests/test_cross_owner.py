"""Cross-owner flow tests — an agent you DON'T own becomes biddable only after a
mutual contact handshake, proven end-to-end OFFLINE on Fakes.

Same-owner siblings are auto-visible to the market (`list_peers`). A DIFFERENT-owner
agent (here a tax bot under "other-org") is invisible to discovery until BOTH sides
complete the contact handshake; once established it shows up in `list_contacts`, so
`discover_pool` — the union of peers ∪ contacts — starts including it, and it becomes
biddable / recruitable like any same-owner specialist.

What these tests pin (ZERO network — one `BandWorld`, a `FakeBandClient` per party):
  - BEFORE the handshake: the cross-owner tax bot is ABSENT from `discover_pool(market)`
    (it is neither a same-owner peer nor an established contact).
  - the inverse handshake (driven via consent's `mutual_link`, i.e. both-sides
    `add_contact`) establishes a mutual contact.
  - AFTER the handshake: the cross-owner tax bot is PRESENT in `discover_pool(market)`.
  - full lifecycle: `run_market_job(..., cross_owner_handles=[tax_handle])` recruits the
    cross-owner tax bot into the work room once it has won a bid.
  - a post-handshake room can add the cross-owner agent as a participant (the recruit
    primitive), independent of the full bid.

Runnable two ways:
  - `python3 tests/test_cross_owner.py`   (no pytest needed — the __main__ runner)
  - `pytest`                              (plain sync test_* functions; each asyncio.runs)
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from agent_exchange.band.client import BandWorld, FakeBandClient
from agent_exchange.band.consent import mutual_link
from agent_exchange.core import MockBackend
from agent_exchange.market.bidding import BiddingAgent
from agent_exchange.market.discovery import discover_pool
from agent_exchange.market.hiring import HiringPolicy
from agent_exchange.market.marketplace import run_market_job
from agent_exchange.market.marketplace_types import AgentIdentity
from agent_exchange.market.reputation import JsonReputationStore
from agent_exchange.market.schema import Job
from agent_exchange.market.selection import CoverageWithinBudget
from agent_exchange.metrics import usdc

# A short MSA preview — enough surface for the (mocked) relevance probes.
CONTRACT = (
    "MASTER SERVICES AGREEMENT\n"
    "1. Liability. Vendor's aggregate liability is capped at fees paid in the prior 12 months.\n"
    "2. Taxes. Fees are exclusive of tax; Client bears all sales, use, and VAT/GST.\n"
)
_TAX_HANDLE = "other-org/tax-clause-bot"

_BID_REPLY = json.dumps({"bid": True, "relevance": 0.9, "price_cents": 200})


def _make_world():
    """A market + a same-owner specialist (self) + a cross-owner tax bot (other-org).

    The tax bot registers under a DIFFERENT owner, so it is NOT a same-owner peer of
    the market — discovery cannot see it until a contact handshake is completed.
    """
    world = BandWorld()
    market = FakeBandClient("m-market", "@self/market", "market", world, owner="self")
    liability = FakeBandClient("s-liability", "@self/liability", "liability", world, owner="self")
    tax = FakeBandClient("o-tax", _TAX_HANDLE, "tax", world, owner="other-org")
    return world, market, liability, tax


# ── before the handshake the cross-owner agent is invisible to discovery ──


def test_cross_owner_agent_is_absent_from_the_pool_before_the_handshake():
    _w, market, _liability, _tax = _make_world()

    pool = asyncio.run(discover_pool(market))
    ids = {a.id for a in pool}

    # The same-owner specialist is discoverable as a peer...
    assert "s-liability" in ids
    # ...but the cross-owner tax bot is NOT (no contact yet).
    assert "o-tax" not in ids


# ── the handshake establishes a mutual contact, flipping discovery ──


def test_handshake_makes_the_cross_owner_agent_discoverable():
    _w, market, _liability, tax = _make_world()

    # Drive the inverse handshake: both sides add_contact → mutual link established.
    # `mutual_link(side_a, a_handle, side_b, b_handle)` has side_a add `a_handle`
    # (the tax bot) and side_b add `b_handle` (the market), auto-approving on the
    # inverse. The load-bearing invariant is the resulting mutual contact edge.
    asyncio.run(mutual_link(market, "@self/market", tax, _TAX_HANDLE))

    # The market now lists the tax bot as an established contact (and vice versa).
    market_contacts = asyncio.run(market.list_contacts())
    tax_contacts = asyncio.run(tax.list_contacts())
    assert "o-tax" in {c["id"] for c in market_contacts}
    assert "m-market" in {c["id"] for c in tax_contacts}

    # And discovery (peers ∪ contacts) now includes BOTH the peer and the contact.
    pool = asyncio.run(discover_pool(market))
    ids = {a.id for a in pool}
    assert "s-liability" in ids
    assert "o-tax" in ids
    # The cross-owner identity carries its handle + name verbatim.
    tax_ident = next(a for a in pool if a.id == "o-tax")
    assert tax_ident == AgentIdentity(id="o-tax", handle=_TAX_HANDLE, name="tax")


# ── post-handshake, the cross-owner agent can be pulled into a room ──


def test_cross_owner_agent_can_be_added_to_a_room_after_the_handshake():
    _w, market, _liability, tax = _make_world()
    asyncio.run(mutual_link(market, "@self/market", tax, _TAX_HANDLE))

    async def _add_to_room() -> set[str]:
        room = await market.create_room("Acme MSA — work room")
        await market.add_participant(room, "o-tax")
        return market.world.rooms[room]["participants"]

    participants = asyncio.run(_add_to_room())
    assert "o-tax" in participants


# ── full lifecycle: the cross-owner tax bot is recruited once it wins a bid ──


def _run_market_with_cross_owner():
    """Drive the full discover→bid→hire→recruit job with a cross-owner tax bidder.

    The tax bot (other-org) is wired as a running `BiddingAgent` with a bid-yes probe,
    so once the handshake makes it discoverable it is invited, bids, is hired (ample
    budget), and recruited into the work room. The same-owner liability specialist
    also bids. Returns the `MarketResult`.
    """
    world, market, liability, tax = _make_world()

    # Drive ONLY the cross-owner bot's half of the handshake (it adds the market →
    # pending). The market's closing half is driven INSIDE run_market_job via
    # `cross_owner_handles` (which calls establish_contact), triggering inverse
    # auto-accept — exactly the production path this param exists for.
    asyncio.run(tax.add_contact("@self/market"))

    with tempfile.TemporaryDirectory() as d:
        reputation = JsonReputationStore(os.path.join(d, "rep.json"))
        agents = [
            BiddingAgent(
                specialty="liability",
                area="liability caps and disclaimers",
                band=liability,
                probe_backend=MockBackend(reply=_BID_REPLY),
                reputation=reputation,
            ),
            BiddingAgent(
                specialty="tax",
                area="tax responsibility and gross-up",
                band=tax,
                probe_backend=MockBackend(reply=_BID_REPLY),
                reputation=reputation,
            ),
        ]
        # Ample budget ($20) so both $2.00 bids (200 cents) are affordable and the
        # cross-owner bot is actually hired within budget, not soft-capped.
        job = Job(
            job_id="acme-1",
            contract=CONTRACT,
            budget_atomic=usdc(20.0),
            title="Audit Acme MSA",
        )
        policy = HiringPolicy(CoverageWithinBudget(), seed=1)
        return asyncio.run(
            run_market_job(
                job,
                market,
                agents,
                policy,
                work_room_title="Acme MSA — hired team",
                cross_owner_handles=[_TAX_HANDLE],
            )
        )


def test_full_market_job_recruits_the_cross_owner_tax_bot():
    result = _run_market_with_cross_owner()

    # Discovery (inside run_market_job) saw the cross-owner contact in the pool.
    assert "o-tax" in {a.id for a in result.pool}
    # The tax bot bid and was hired (ample budget).
    assert "tax" in {b.worker for b in result.bids}
    assert "tax" in {h.worker for h in result.decision.hired}
    # And it was recruited into the dedicated work room.
    assert "tax" in result.team.recruited


def _run_all():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"  ✓ {fn.__name__}")
    print(f"\n{len(fns)} passed")


if __name__ == "__main__":
    _run_all()
