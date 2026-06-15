"""Offline tests for the SERVER's live cross-owner recruit beat (server/app.py).

These pin the #1 hero moment wired into ``_build_live_context``: when
``BAND_CROSS_OWNER_SPECIALTY`` designates a roster specialty whose Band key is a SECOND
account's, the market runs the REAL contact-consent handshake (inverse auto-accept) with
that agent BEFORE adding it to the work room, marks its pool entry ``cross_owner=True``,
and records a recruit narration the live SSE stream emits as a ``room_message``.

ALL OFFLINE — zero network. The live transports are injected at the boundary with the
project's own fakes (``FakeBandClient`` + one shared ``BandWorld``, exactly as
``tests/test_cross_owner.py`` / ``test_contacts.py`` do); ``make_backend`` and the x402
gate are stubbed so no provider/chain is touched.

Coverage:
  * cross-owner ON: the cross-owner agent ends up a market CONTACT, a room PARTICIPANT,
    and its pool entry has ``cross_owner=True`` + an org owner label + a recruit narration;
  * every OTHER specialist stays same-owner (``cross_owner=False``, ``owner="self"``);
  * cross-owner OFF (specialty unset): NO handshake, all self, no crash, no narration;
  * a FAILING handshake degrades gracefully — the run still builds, the agent is recruited
    as same-owner (no cross-owner marker), no exception escapes.
"""

from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))

import pytest

import app as server_app
import cross_owner as xowner
from agent_exchange.band.client import BandWorld, FakeBandClient

# The designated cross-owner specialty for these tests + its (other-org) handle.
_XSPEC = "tax"
_XHANDLE = "other-org/tax-clause-bot"
_MARKET_HANDLE = "self/market"


# ---------------------------------------------------------------------------
# Boundary injection: a fake Band world + stubbed provider / x402 gate.
# ---------------------------------------------------------------------------


class _FakeWorld:
    """Maps each Band api_key to a distinct FakeBandClient over one shared BandWorld.

    The market + same-owner specialists share owner ``"self"`` (auto-visible peers); the
    cross-owner agent registers under owner ``"other-org"`` so it is NOT a peer — exactly
    the condition the contact handshake exists to bridge.
    """

    def __init__(self, *, cross_owner_pre_adds_market: bool = True,
                 break_handshake: bool = False) -> None:
        self.world = BandWorld()
        self._break = break_handshake
        self._pre_add = cross_owner_pre_adds_market
        self._by_key: dict[str, FakeBandClient] = {}
        # The market (created first so its key is deterministic).
        self.market = self._register("market-key", "m-market", _MARKET_HANDLE,
                                     "market", owner="self")
        # The cross-owner agent (other-org) — its key is the SECOND account's.
        self.cross = self._register(f"BAND_SPECIALIST_{_XSPEC.upper()}_KEY",
                                    "o-tax", _XHANDLE, "Tax Auditor", owner="other-org")

    def _register(self, key, aid, handle, name, *, owner) -> FakeBandClient:
        client = FakeBandClient(aid, handle, name, self.world, owner=owner)
        if self._break:
            # Force the handshake to raise so we can prove graceful degradation.
            async def _boom(_h):  # noqa: ANN001
                raise RuntimeError("simulated Band handshake failure")
            client.add_contact = _boom  # type: ignore[assignment]
        self._by_key[key] = client
        return client

    def factory(self, api_key: str) -> FakeBandClient:
        client = self._by_key.get(api_key)
        if client is None:
            # An un-pre-registered specialist key (e.g. a same-owner peer) → register on
            # the fly as a self-owner agent so the build proceeds.
            aid = f"self-{api_key}"
            client = self._register(api_key, aid, f"self/{aid}", aid, owner="self")
        return client


class _StubBackend:
    """A no-op model backend (constructed in place of a real provider)."""


class _StubGate:
    async def ensure_permit2_approval(self):
        return None


def _wire(monkeypatch, fake: _FakeWorld) -> None:
    """Patch the live transports in the app module to the fake world + stubs."""
    monkeypatch.setattr(server_app, "make_backend", lambda *a, **k: _StubBackend())
    # `_build_live_context` imports make_http_band_client / make_x402_gate locally from
    # their modules, so patch them at the source module.
    import agent_exchange.band.http_client as http_client
    import agent_exchange.payments.x402_gate as x402_gate

    monkeypatch.setattr(http_client, "make_http_band_client", fake.factory)
    monkeypatch.setattr(x402_gate, "make_x402_gate", lambda *a, **k: _StubGate())
    # Only the cross-owner specialty has a key (keeps the roster small + deterministic).
    monkeypatch.setattr(
        http_client, "specialist_band_keys",
        lambda: {_XSPEC: f"BAND_SPECIALIST_{_XSPEC.upper()}_KEY"},
    )
    # The market key + dummy env so make_backend / env reads don't blow up.
    monkeypatch.setenv("BAND_MARKET_KEY", "market-key")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("SELLER_PAYTO_ADDRESS", "0x" + "0" * 40)
    monkeypatch.setenv("EVM_PRIVATE_KEY", "0x" + "1" * 64)


def _build(monkeypatch, fake: _FakeWorld):
    _wire(monkeypatch, fake)
    return asyncio.run(server_app._build_live_context("contract-audit", "A short MSA.", 0.20))


# ---------------------------------------------------------------------------
# cross-owner ON — the full hero beat
# ---------------------------------------------------------------------------


def test_cross_owner_on_establishes_contact_and_marks_the_pool(monkeypatch):
    monkeypatch.setenv("BAND_CROSS_OWNER_SPECIALTY", _XSPEC)
    monkeypatch.setenv(f"BAND_OWNER2_{_XSPEC.upper()}_HANDLE", _XHANDLE)
    fake = _FakeWorld()

    ctx = _build(monkeypatch, fake)

    # 1. The cross-owner agent is now an ESTABLISHED contact of the market (handshake ran).
    market_contacts = asyncio.run(fake.market.list_contacts())
    assert "o-tax" in {c["id"] for c in market_contacts}, "handshake did not establish the contact"

    # 2. It is a PARTICIPANT in the work room (recruited after the handshake).
    participants = fake.world.rooms[ctx.work_room_id]["participants"]
    assert "o-tax" in participants, "cross-owner agent was not added to the work room"

    # 3. Its pool entry is marked cross_owner with an org owner label.
    tax_entry = next(p for p in ctx.pool if p["id"] == "o-tax")
    assert tax_entry["cross_owner"] is True
    assert tax_entry["owner"] == "other-org"

    # 4. A recruit narration was recorded (the room_message the live stream emits).
    assert ctx.recruit_messages, "no cross-owner recruit narration was recorded"
    narration = ctx.recruit_messages[0]
    assert narration["sender"] == "market"
    assert "approved" in narration["content"] and "other-org" in narration["content"]


def test_cross_owner_on_keeps_other_specialists_same_owner(monkeypatch):
    # Add a same-owner peer alongside the cross-owner specialty.
    import agent_exchange.band.http_client as http_client

    monkeypatch.setenv("BAND_CROSS_OWNER_SPECIALTY", _XSPEC)
    monkeypatch.setenv(f"BAND_OWNER2_{_XSPEC.upper()}_HANDLE", _XHANDLE)
    fake = _FakeWorld()
    # A same-owner liability specialist (self) registered under its key.
    fake._register("BAND_SPECIALIST_LIABILITY_KEY", "s-liability", "self/liability",
                   "Liability", owner="self")

    _wire(monkeypatch, fake)
    monkeypatch.setattr(
        http_client, "specialist_band_keys",
        lambda: {"liability": "BAND_SPECIALIST_LIABILITY_KEY",
                 _XSPEC: f"BAND_SPECIALIST_{_XSPEC.upper()}_KEY"},
    )
    ctx = asyncio.run(server_app._build_live_context("contract-audit", "A short MSA.", 0.20))

    liab = next(p for p in ctx.pool if p["id"] == "s-liability")
    assert liab["cross_owner"] is False and liab["owner"] == "self"
    tax = next(p for p in ctx.pool if p["id"] == "o-tax")
    assert tax["cross_owner"] is True


# ---------------------------------------------------------------------------
# cross-owner OFF — no handshake, all self, no crash
# ---------------------------------------------------------------------------


def test_cross_owner_off_when_specialty_unset(monkeypatch):
    monkeypatch.delenv("BAND_CROSS_OWNER_SPECIALTY", raising=False)
    monkeypatch.setenv("BAND_CROSS_OWNER_SPECIALTY", "")  # explicitly blank → disabled
    monkeypatch.setenv(f"BAND_OWNER2_{_XSPEC.upper()}_HANDLE", _XHANDLE)
    fake = _FakeWorld()

    ctx = _build(monkeypatch, fake)

    # No handshake ran: the cross-owner agent is NOT a contact of the market.
    assert asyncio.run(fake.market.list_contacts()) == []
    # Its pool entry exists (recruited via its key) but is same-owner, not cross.
    tax_entry = next(p for p in ctx.pool if p["id"] == "o-tax")
    assert tax_entry["cross_owner"] is False
    assert tax_entry["owner"] == "self"
    # No recruit narration on the same-owner path.
    assert ctx.recruit_messages == []


def test_cross_owner_off_when_handle_missing(monkeypatch):
    # Specialty set but the handle env is absent → disabled (no crash, all self).
    monkeypatch.setenv("BAND_CROSS_OWNER_SPECIALTY", _XSPEC)
    monkeypatch.delenv(f"BAND_OWNER2_{_XSPEC.upper()}_HANDLE", raising=False)
    fake = _FakeWorld()

    ctx = _build(monkeypatch, fake)

    assert asyncio.run(fake.market.list_contacts()) == []
    tax_entry = next(p for p in ctx.pool if p["id"] == "o-tax")
    assert tax_entry["cross_owner"] is False
    assert ctx.recruit_messages == []


# ---------------------------------------------------------------------------
# graceful failure — a broken handshake never crashes the build
# ---------------------------------------------------------------------------


def test_failing_handshake_degrades_to_same_owner(monkeypatch):
    monkeypatch.setenv("BAND_CROSS_OWNER_SPECIALTY", _XSPEC)
    monkeypatch.setenv(f"BAND_OWNER2_{_XSPEC.upper()}_HANDLE", _XHANDLE)
    fake = _FakeWorld(break_handshake=True)  # add_contact raises on every client

    # The build must still complete (no exception escapes).
    ctx = _build(monkeypatch, fake)

    # The cross-owner agent is still recruited (its key is in the roster) but treated as
    # same-owner — the contact was never established and there is no narration.
    tax_entry = next(p for p in ctx.pool if p["id"] == "o-tax")
    assert tax_entry["cross_owner"] is False
    assert tax_entry["owner"] == "self"
    assert "o-tax" in fake.world.rooms[ctx.work_room_id]["participants"]
    assert ctx.recruit_messages == []


# ---------------------------------------------------------------------------
# the pure config / label helpers
# ---------------------------------------------------------------------------


def test_owner_label_for_handles_org_prefixes():
    assert xowner.owner_label_for("other-org/tax-clause-bot") == "other-org"
    assert xowner.owner_label_for("@acme/bot") == "acme"
    assert xowner.owner_label_for("lonehandle") == "other"
    assert xowner.owner_label_for("") == "other"


def test_cross_owner_specialty_default_and_blank(monkeypatch):
    monkeypatch.delenv("BAND_CROSS_OWNER_SPECIALTY", raising=False)
    assert xowner.cross_owner_specialty() == "tax"  # default
    monkeypatch.setenv("BAND_CROSS_OWNER_SPECIALTY", "  ")
    assert xowner.cross_owner_specialty() == ""  # blank → disabled
    monkeypatch.setenv("BAND_CROSS_OWNER_SPECIALTY", "indemnity")
    assert xowner.cross_owner_specialty() == "indemnity"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
