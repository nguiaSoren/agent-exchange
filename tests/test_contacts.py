"""Contact-consent tests — the `FakeBandClient` consent model, proven OFFLINE.

Same-owner siblings are auto-visible (`list_peers`); a DIFFERENT-owner agent is only
reachable after a mutual contact handshake. These tests pin the four behaviours of
that handshake on the fake (the locked spec mirrored from Band's /contacts surface),
with ZERO network — one shared `BandWorld` and a `FakeBandClient` per party:

  1. `add_contact` to an UNKNOWN handle → an error verdict (no request recorded).
  2. One-sided `add_contact` → `{"status":"pending"}`; the TARGET sees the incoming
     request in `list_contact_requests` and neither side is a contact yet.
  3. INVERSE auto-accept: B requests A (pending), then A requests B → Band sees the
     inverse pending request and AUTO-APPROVES → both sides are now mutual contacts.
  4. EXPLICIT approve: A requests B (pending), B `respond_to_contact_request(approve)`
     → both sides are mutual contacts.

Runnable two ways:
  - `python3 tests/test_contacts.py`   (no pytest needed — the __main__ runner)
  - `pytest`                           (plain sync test_* functions; each asyncio.runs)
"""

from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from agent_exchange.band.client import BandWorld, FakeBandClient


def _two_parties():
    """A shared world with two agents A and B (owners are irrelevant to the handshake).

    The consent surface is owner-agnostic on the fake: `add_contact` resolves by
    handle regardless of owner, so the same flow drives both same-owner and
    cross-owner handshakes. Cross-owner end-to-end is covered in test_cross_owner.py.
    """
    world = BandWorld()
    a = FakeBandClient("a", "@x/a", "alpha", world)
    b = FakeBandClient("b", "@x/b", "bravo", world)
    return world, a, b


# ── 1. add_contact to an unknown handle → error, no request recorded ──


def test_add_contact_to_unknown_handle_returns_an_error():
    world, a, _b = _two_parties()

    result = asyncio.run(a.add_contact("@x/nobody"))

    assert result["status"] == "error"
    assert result.get("reason") == "unknown_handle"
    # No pending request was recorded for a bogus handle.
    assert world.contact_requests == []


# ── 2. one-sided add_contact → pending; the target sees the incoming request ──


def test_one_sided_add_contact_is_pending_and_visible_to_the_target():
    _world, a, b = _two_parties()

    result = asyncio.run(a.add_contact("@x/b"))
    assert result["status"] == "pending"

    # The TARGET (b) sees the incoming request addressed to it.
    requests = asyncio.run(b.list_contact_requests())
    assert len(requests) == 1
    assert requests[0]["from_id"] == "a"
    assert requests[0]["from_handle"] == "@x/a"

    # The REQUESTER does not see it as incoming (it is outbound for a).
    assert asyncio.run(a.list_contact_requests()) == []

    # Pending ≠ established: neither side is a contact yet.
    assert asyncio.run(a.list_contacts()) == []
    assert asyncio.run(b.list_contacts()) == []


# ── 3. inverse auto-accept: B adds A (pending), then A adds B → approved ──


def test_inverse_request_auto_approves_into_a_mutual_contact():
    _world, a, b = _two_parties()

    # B requests A first → pending (no inverse exists yet).
    assert asyncio.run(b.add_contact("@x/a"))["status"] == "pending"

    # A now requests B → Band finds B's pending inverse request and auto-approves.
    assert asyncio.run(a.add_contact("@x/b"))["status"] == "approved"

    # Both sides are now mutual contacts.
    a_contacts = asyncio.run(a.list_contacts())
    b_contacts = asyncio.run(b.list_contacts())
    assert [c["id"] for c in a_contacts] == ["b"]
    assert [c["id"] for c in b_contacts] == ["a"]
    # The pending inverse request was consumed by the auto-approve.
    assert asyncio.run(a.list_contact_requests()) == []
    assert asyncio.run(b.list_contact_requests()) == []


# ── 4. explicit approve: A adds B (pending), B approves → mutual contact ──


def test_explicit_approve_establishes_a_mutual_contact():
    _world, a, b = _two_parties()

    # A requests B → pending.
    assert asyncio.run(a.add_contact("@x/b"))["status"] == "pending"
    # B explicitly approves the request from A's handle.
    resp = asyncio.run(b.respond_to_contact_request("@x/a", "approve"))
    assert resp["status"] == "approved"

    # Both sides are now mutual contacts; the request is gone.
    assert [c["id"] for c in asyncio.run(a.list_contacts())] == ["b"]
    assert [c["id"] for c in asyncio.run(b.list_contacts())] == ["a"]
    assert asyncio.run(b.list_contact_requests()) == []


# ── 4b. explicit reject: the request is dropped, no contact is formed ──


def test_explicit_reject_drops_the_request_without_linking():
    _world, a, b = _two_parties()

    assert asyncio.run(a.add_contact("@x/b"))["status"] == "pending"
    resp = asyncio.run(b.respond_to_contact_request("@x/a", "reject"))
    assert resp["status"] == "rejected"

    # No contact formed on either side, and the request is cleared.
    assert asyncio.run(a.list_contacts()) == []
    assert asyncio.run(b.list_contacts()) == []
    assert asyncio.run(b.list_contact_requests()) == []


def _run_all():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"  ✓ {fn.__name__}")
    print(f"\n{len(fns)} passed")


if __name__ == "__main__":
    _run_all()
