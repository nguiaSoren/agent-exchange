"""Recruiting-layer tests — the market gathers ONLY the hired team into a dedicated
work room, proven OFFLINE.

After hiring picks a team (`HiringDecision`), `recruit_team` creates a NEW work room,
adds as participants ONLY the hired workers it can identify (those present in
`mention_for`), posts a kickoff @mention to them, and returns a `RecruitedTeam`
splitting the hired into `recruited` (added) vs `skipped` (hired but no known
identity, so unaddable). Declined workers are never touched. We drive it with ZERO
network: one shared `BandWorld` and a market `FakeBandClient`, then inspect the
world's room state directly.

The crafted scenario: two hired (liability, ip) + one declined (tax). `mention_for`
covers liability + tax but DELIBERATELY OMITS ip — so liability is recruited, ip is
skipped (no identity), and tax (declined) is never added regardless of having an
identity.

Runnable two ways:
  - `python3 tests/test_recruiting.py`   (no pytest needed — the __main__ runner)
  - `pytest`                             (plain sync test_* functions; each asyncio.runs)
"""

from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from agent_exchange.band.client import BandWorld, FakeBandClient
from agent_exchange.market.hiring_types import Hire, HiringDecision
from agent_exchange.market.marketplace_types import RecruitedTeam
from agent_exchange.market.recruiting import recruit_team
from agent_exchange.metrics import usdc

_ATOMIC_PER_CENT = 10**4


def _mention(client: FakeBandClient) -> dict:
    """The @mention dict Band routing expects for a given fake client."""
    return {"id": client.agent_id, "handle": client.handle, "name": client.name}


def _decision() -> HiringDecision:
    """Two hired (liability, ip) + one declined (tax)."""
    return HiringDecision(
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


def _setup():
    """Shared world + market/specialist clients + a mention_for that omits 'ip'.

    'ip' is a hired worker, but it is intentionally absent from `mention_for`, so it
    must land in `skipped`. 'tax' is declined yet HAS an identity — proving declined
    workers are excluded on the hired/declined axis, not for lack of an identity.
    """
    world = BandWorld()
    market = FakeBandClient("m", "@x/market", "market", world)
    liability = FakeBandClient("liability", "@x/liability", "liability", world)
    ip = FakeBandClient("ip", "@x/ip", "ip", world)
    tax = FakeBandClient("tax", "@x/tax", "tax", world)

    # Covers a hired worker (liability) + the declined one (tax); OMITS hired 'ip'.
    mention_for = {
        "liability": _mention(liability),
        "tax": _mention(tax),
    }
    return world, market, ip, mention_for


# ── recruit_team splits hired into recruited vs skipped ──


def test_recruit_team_recruits_identified_hires_and_skips_the_unknown_one():
    _world, market, _ip, mention_for = _setup()

    team = asyncio.run(recruit_team(_decision(), market, mention_for=mention_for))

    assert isinstance(team, RecruitedTeam)
    # liability had an identity → recruited; ip was hired but unknown → skipped.
    assert team.recruited == ("liability",)
    assert team.skipped == ("ip",)
    assert team.n_recruited == 1


# ── a NEW work room is created and only recruited workers join it ──


def test_recruit_team_creates_a_new_room_with_only_the_recruited_as_participants():
    world, market, ip, mention_for = _setup()

    team = asyncio.run(recruit_team(_decision(), market, mention_for=mention_for))

    # A brand-new room was created (registered in the shared world).
    assert team.work_room_id in world.rooms
    participants = world.rooms[team.work_room_id]["participants"]

    # The recruited worker is a participant (added by its mention id).
    assert "liability" in participants
    # The skipped hire (no identity) was NOT added.
    assert "ip" not in participants
    # The DECLINED worker is NOT a participant, even though it has an identity.
    assert "tax" not in participants
    # Only the market (room creator) + the single recruited worker are present.
    assert participants == {"m", "liability"}
    # ip (skipped) never received a kickoff message either.
    assert asyncio.run(ip.get_next_message(team.work_room_id)) is None


def _run_all():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"  ✓ {fn.__name__}")
    print(f"\n{len(fns)} passed")


if __name__ == "__main__":
    _run_all()
