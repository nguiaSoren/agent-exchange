"""Discovery-layer tests — the market finds its agent pool via Band, proven OFFLINE.

`discover_pool` asks the market's OWN Band client for its pool, which is the UNION
of two sources: same-owner siblings (`list_peers`) ∪ established cross-owner contacts
(`list_contacts`). It maps each `{id, handle, name}` into an `AgentIdentity`, dedupes
by id, and always drops the market's own identity plus any explicitly excluded ids.
We drive it with ZERO network: one shared `BandWorld` and three `FakeBandClient`s
(market + two specialists) that register themselves into that world as same-owner
siblings, so the market discovers exactly the two OTHER agents as peers.

The contract under test (`market/discovery.py`):
  - returns the other same-owner agents as `AgentIdentity` (excludes the market),
  - `exclude=` removes a given id from the pool,
  - fail-safe per source: if EITHER `list_peers()` or `list_contacts()` raises, that
    source contributes `[]` and the other still counts — discovery never crashes.

Runnable two ways:
  - `python3 tests/test_discovery.py`   (no pytest needed — the __main__ runner)
  - `pytest`                            (plain sync test_* functions; each asyncio.runs)
"""

from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from agent_exchange.band.client import BandWorld, FakeBandClient
from agent_exchange.market.discovery import discover_pool
from agent_exchange.market.marketplace_types import AgentIdentity


def _world_with_market_and_two_specialists():
    """A shared world holding a market client + two specialist clients.

    Every `FakeBandClient` constructed on the SAME `BandWorld` registers itself,
    so each one's `list_contacts()` returns the OTHER agents in that world. Ids are
    chosen so the natural sort order (b-ip < c-liability) is deterministic and
    visibly distinct from the market's own id.
    """
    world = BandWorld()
    market = FakeBandClient("a-market", "@x/market", "market", world)
    ip = FakeBandClient("b-ip", "@x/ip", "ip", world)
    liability = FakeBandClient("c-liability", "@x/liability", "liability", world)
    return world, market, ip, liability


# ── discover_pool returns the OTHER agents (excludes the market itself) ──


def test_discover_pool_returns_the_two_specialists_excluding_the_market():
    _world, market, _ip, _liability = _world_with_market_and_two_specialists()

    pool = asyncio.run(discover_pool(market))

    # Exactly the two specialists, as AgentIdentity, id-sorted; the market is gone.
    assert all(isinstance(a, AgentIdentity) for a in pool)
    assert [a.id for a in pool] == ["b-ip", "c-liability"]
    assert "a-market" not in {a.id for a in pool}
    # Each AgentIdentity carries the registered handle + name verbatim.
    assert pool[0] == AgentIdentity(id="b-ip", handle="@x/ip", name="ip")
    assert pool[1] == AgentIdentity(id="c-liability", handle="@x/liability", name="liability")


# ── exclude= removes a given id from the discovered pool ──


def test_discover_pool_honours_the_exclude_set():
    _world, market, _ip, _liability = _world_with_market_and_two_specialists()

    pool = asyncio.run(discover_pool(market, exclude={"b-ip"}))

    # The excluded specialist is dropped on top of the always-excluded market id.
    assert [a.id for a in pool] == ["c-liability"]
    assert "b-ip" not in {a.id for a in pool}


# ── fail-safe: a source that raises contributes [], the other still counts ──


class _RaisingContactsClient(FakeBandClient):
    """A market client whose `list_contacts` always raises — proves the fail-safe.

    `me()` and `list_peers()` still work, so same-owner discovery is unaffected; the
    only failure is in CONTACT discovery. The contract is to swallow it (that source
    contributes nothing, defaulting to empty) while the peers source still counts.
    """

    async def list_contacts(self) -> list[dict]:
        raise RuntimeError("Band /contacts exploded")


class _RaisingPeersClient(FakeBandClient):
    """A market client whose `list_peers` always raises — the symmetric fail-safe.

    The peers source degrades to empty; established contacts (if any) still count.
    """

    async def list_peers(self) -> list[dict]:
        raise RuntimeError("Band /peers exploded")


def test_discover_pool_survives_a_raising_list_contacts_via_the_peers_source():
    world = BandWorld()
    market = _RaisingContactsClient("a-market", "@x/market", "market", world)
    # Same-owner siblings come from list_peers, which is unaffected by the raise.
    FakeBandClient("b-ip", "@x/ip", "ip", world)
    FakeBandClient("c-liability", "@x/liability", "liability", world)

    pool = asyncio.run(discover_pool(market))

    # list_contacts raised → contributes nothing (established contacts default empty);
    # the peers source still yields the two same-owner siblings, no exception escaped.
    assert [a.id for a in pool] == ["b-ip", "c-liability"]


def test_discover_pool_fails_safe_to_empty_when_both_sources_are_empty_or_raise():
    world = BandWorld()
    # list_peers raises AND there are no established contacts → empty pool, no crash.
    market = _RaisingPeersClient("a-market", "@x/market", "market", world)
    FakeBandClient("b-ip", "@x/ip", "ip", world)  # a sibling only the peers source sees

    pool = asyncio.run(discover_pool(market))

    # The raising source degrades to empty; nothing in contacts → empty pool, no raise.
    assert pool == []


def _run_all():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"  ✓ {fn.__name__}")
    print(f"\n{len(fns)} passed")


if __name__ == "__main__":
    _run_all()
