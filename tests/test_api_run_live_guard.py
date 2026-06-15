"""Offline tests for the LIVE run hardening — single-flight, daily caps, the seeded
fabricator catch, and graceful failure (all the things that make ``POST /api/run``
mode=live safe to expose publicly).

All offline: the single-flight + cap tests drive the real ``/api/run`` route via
FastAPI's ``TestClient`` but force ``_live_keys_present`` True and stub the live runner,
so NO Band/x402/provider network is hit; the seeded-fabricator test runs the REAL
``collaborate_in_room`` + ``settle_job`` against the offline ``KeyedVerifierBackend`` +
``SimGate`` (exactly as sim.py / test_api_audit.py do).

Coverage:
  * live with keys absent -> 429 live_unavailable;
  * single-flight: a second live request while one is active -> 429 live_busy;
  * daily run-count cap -> 429 live_cap_reached after N;
  * daily $ cap -> 429 live_cap_reached when over budget;
  * the seeded fabricator -> an ``unsupported``-graded finding -> gate_passed False ($0);
  * the seeded finding is flagged (worker id seeded-probe);
  * sim mode is unrestricted by the live guard (still streams).
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

import app as server_app
import live_guard


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _fresh_live_guard():
    """Reset the process-global live guard before/after each test."""
    live_guard.reset_live_guard()
    yield
    live_guard.reset_live_guard()


@pytest.fixture
def client() -> TestClient:
    return TestClient(server_app.app)


def _force_live_keys(monkeypatch, present: bool = True) -> None:
    """Make the route believe (or not) that the live keys are configured."""
    monkeypatch.setattr(server_app, "_live_keys_present", lambda: present)


async def _fake_run_job(kind, document, budget_usd, requested_mode):
    """A stand-in live run that streams a minimal lifecycle, no network/spend."""
    yield "document", {"kind": kind, "title": "t", "document_text": "x", "budget_usd": 0.2}
    yield "done", {"gate_passed": True, "pay_fraction": 1.0,
                   "total_settled_usd": 0.0, "total_withheld_usd": 0.0,
                   "catch_summary": "ok"}


# ---------------------------------------------------------------------------
# Live availability + single-flight + caps
# ---------------------------------------------------------------------------


def test_live_unavailable_when_keys_absent(client, monkeypatch):
    _force_live_keys(monkeypatch, present=False)
    r = client.post("/api/run", json={"kind": "contract-audit", "mode": "live"})
    assert r.status_code == 429, r.text
    assert r.json()["error"] == "live_unavailable"


def test_single_flight_returns_busy(client, monkeypatch):
    # Simulate an active live run by taking the single-flight flag directly, then a
    # second live request must be refused with live_busy (before any streaming).
    _force_live_keys(monkeypatch, present=True)
    monkeypatch.setattr(server_app, "_project_live_cost", lambda *a, **k: 0.01)

    guard = live_guard.get_live_guard()
    held = guard.try_acquire(projected_usd=0.01)
    assert held.admitted  # one run is now "in flight"

    r = client.post("/api/run", json={"kind": "contract-audit", "mode": "live"})
    assert r.status_code == 429, r.text
    assert r.json()["error"] == "live_busy"

    # Releasing frees the flag for the next run.
    guard.release(held)
    assert not guard.is_active()


def test_daily_run_count_cap(client, monkeypatch):
    _force_live_keys(monkeypatch, present=True)
    monkeypatch.setattr(server_app, "_project_live_cost", lambda *a, **k: 0.0)
    # Tiny run-count cap so we hit it fast; each call fully completes (flag released)
    # because the stubbed runner streams + ends, so single-flight never blocks here.
    monkeypatch.setattr(live_guard, "LIVE_DAILY_RUNS", 2)
    monkeypatch.setattr(server_app, "run_job", _fake_run_job)

    ok1 = client.post("/api/run", json={"kind": "contract-audit", "mode": "live"})
    assert ok1.status_code == 200, ok1.text
    ok2 = client.post("/api/run", json={"kind": "contract-audit", "mode": "live"})
    assert ok2.status_code == 200, ok2.text
    # Third over the cap.
    over = client.post("/api/run", json={"kind": "contract-audit", "mode": "live"})
    assert over.status_code == 429, over.text
    assert over.json()["error"] == "live_cap_reached"


def test_daily_dollar_cap(client, monkeypatch):
    _force_live_keys(monkeypatch, present=True)
    monkeypatch.setattr(server_app, "run_job", _fake_run_job)
    # Each run projects $1.00; cap the day at $1.50 -> first OK, second over.
    monkeypatch.setattr(server_app, "_project_live_cost", lambda *a, **k: 1.0)
    monkeypatch.setattr(live_guard, "LIVE_DAILY_CAP_USD", Decimal("1.50"))
    # Rebuild the singleton so it picks up the patched cap.
    live_guard.reset_live_guard()

    r1 = client.post("/api/run", json={"kind": "contract-audit", "mode": "live"})
    assert r1.status_code == 200, r1.text
    r2 = client.post("/api/run", json={"kind": "contract-audit", "mode": "live"})
    assert r2.status_code == 429, r2.text
    assert r2.json()["error"] == "live_cap_reached"


def test_sim_mode_unrestricted_by_live_guard(client, monkeypatch):
    # Even with the single-flight flag held, a SIM request streams (sim has no guards).
    guard = live_guard.get_live_guard()
    held = guard.try_acquire(projected_usd=0.0)
    assert held.admitted

    r = client.post("/api/run", json={"kind": "contract-audit", "mode": "sim"})
    assert r.status_code == 200, r.text
    assert "event: document" in r.text
    guard.release(held)


def test_live_release_after_run_frees_single_flight(client, monkeypatch):
    # A completed live run must release the flag so the NEXT live run is admitted.
    _force_live_keys(monkeypatch, present=True)
    monkeypatch.setattr(server_app, "_project_live_cost", lambda *a, **k: 0.0)
    monkeypatch.setattr(server_app, "run_job", _fake_run_job)

    r1 = client.post("/api/run", json={"kind": "contract-audit", "mode": "live"})
    assert r1.status_code == 200
    assert not live_guard.get_live_guard().is_active()  # released after the stream
    r2 = client.post("/api/run", json={"kind": "contract-audit", "mode": "live"})
    assert r2.status_code == 200  # not live_busy — the prior run released


def test_live_run_error_releases_single_flight(client, monkeypatch):
    # If the live run raises, the stream emits a clean error event AND releases the flag.
    _force_live_keys(monkeypatch, present=True)
    monkeypatch.setattr(server_app, "_project_live_cost", lambda *a, **k: 0.0)

    async def _boom(*a, **k):
        raise RuntimeError("band exploded")
        yield  # pragma: no cover — makes this an async generator

    monkeypatch.setattr(server_app, "run_job", _boom)
    r = client.post("/api/run", json={"kind": "contract-audit", "mode": "live"})
    assert r.status_code == 200  # the stream itself opened
    assert "event: error" in r.text
    assert "band exploded" in r.text
    assert not live_guard.get_live_guard().is_active()  # flag released in finally


# ---------------------------------------------------------------------------
# The seeded fabricator -> unsupported -> gate fails -> $0, and is flagged
# ---------------------------------------------------------------------------


def test_seeded_fabricator_caught_and_gate_fails():
    """The seeded probe's FALSE finding -> graded unsupported -> job gate fails ($0)."""
    import asyncio

    asyncio.run(_seeded_fabricator_caught_and_gate_fails())


async def _seeded_fabricator_caught_and_gate_fails():
    from agent_exchange.audit.room_audit import collaborate_in_room
    from agent_exchange.audit.room_audit_types import CollaborationMember, ReporterMember
    from agent_exchange.band.client import BandWorld, FakeBandClient
    from agent_exchange.market.hiring_types import Hire
    from agent_exchange.metrics import usdc
    from agent_exchange.payments.settlement import settle_job
    from agent_exchange.verify.schema import LENIENT, Verdict
    from agent_exchange.verify.verifier import Verifier

    from sim import KeyedVerifierBackend, SimGate

    # The seeded fabricator for a contract-audit, plus one genuine confirmed worker.
    fab = server_app._SeededFabricator("contract-audit")
    fab_claim = fab._finding.claim
    assert fab.name == server_app.SEEDED_PROBE_ID

    world = BandWorld()
    market = FakeBandClient("market", "market", "Market", world)
    probe_band = FakeBandClient("probe", "probe", "Probe", world)
    reporter_band = FakeBandClient("reporter", "reporter", "Reporter", world)
    rid = await market.create_room("work")
    await market.add_participant(rid, "probe")
    await market.add_participant(rid, "reporter")

    team = [CollaborationMember(specialty=server_app.SEEDED_PROBE_ID,
                               area="seeded test", band=probe_band, auditor=fab)]
    reporter = ReporterMember(
        band=reporter_band,
        reporter=_NoopReporter(),
        mention={"id": "reporter", "handle": "reporter", "name": "Reporter"},
    )

    # The REAL verifier backend, keyed to grade the fabricated claim unsupported.
    verifier = Verifier(
        KeyedVerifierBackend({fab_claim: ("unsupported", 0.9, None)}),
        document_label="contract", ablation_gate=True,
    )

    result = await collaborate_in_room(rid, "A short MSA with no clause 12.", team,
                                       reporter, verifier)

    # The seeded finding was graded unsupported.
    seeded = [af for af in result.all_audited
              if af.finding.worker == server_app.SEEDED_PROBE_ID]
    assert seeded, "seeded probe finding missing from the audit"
    assert all(af.verdict.verdict is Verdict.UNSUPPORTED for af in seeded)

    # The job-level gate fails -> $0 settled.
    hires = [Hire(worker=server_app.SEEDED_PROBE_ID, price_atomic=usdc(0.02),
                  value=0.0, relevance=0.0)]
    settlement = await settle_job(
        SimGate(), result, hires, {server_app.SEEDED_PROBE_ID: "0x" + "0" * 40},
        policy=LENIENT,
    )
    assert settlement.gate_passed is False
    assert settlement.total_settled_atomic == 0


# ---------------------------------------------------------------------------
# LIVE collaborate phase streams per-agent `progress` events
# ---------------------------------------------------------------------------


def test_live_run_emits_progress_events_during_collaborate(monkeypatch):
    """The LIVE branch must emit one `progress` {worker, done:true} per member as each
    member's in-room audit completes (driven by on_member_complete), and never deadlock."""
    import asyncio

    # Build the live context from the offline sim world (real team/reporter/verifier
    # against fakes) so the whole live lifecycle runs networkless.
    async def _fake_live_ctx(kind, document, budget_usd):
        return await server_app._build_sim_context(kind, document)

    monkeypatch.setattr(server_app, "_build_live_context", _fake_live_ctx)

    # Wrap the real collaborate so we KNOW the callback fires for the members we
    # name (independent of how many specialists the sim seeds): fire two completions
    # explicitly, then delegate to the real function (which also fires per member).
    real_collaborate = server_app.collaborate_in_room

    async def _wrapped(work_room_id, contract, team, reporter, verifier, *,
                       on_member_complete=None, **kw):
        if on_member_complete is not None:
            await on_member_complete("liability", [])
            await on_member_complete("termination", [])
        return await real_collaborate(
            work_room_id, contract, team, reporter, verifier,
            on_member_complete=on_member_complete, **kw,
        )

    monkeypatch.setattr(server_app, "collaborate_in_room", _wrapped)

    async def _collect():
        out = []
        async for ev, data in server_app.run_job(
            "contract-audit", document="", budget_usd=0.20, requested_mode="live"
        ):
            out.append((ev, data))
        return out

    loop = asyncio.new_event_loop()
    try:
        events = loop.run_until_complete(_collect())
    finally:
        loop.close()

    progress = [d for n, d in events if n == "progress"]
    # At least the two we forced; every progress event has the documented shape.
    assert len(progress) >= 2
    for p in progress:
        assert p["done"] is True
        assert isinstance(p["worker"], str) and p["worker"]
    workers = {p["worker"] for p in progress}
    assert {"liability", "termination"} <= workers
    # As each member completes, the live path also streams a room line with WHAT that
    # agent wrote (granular), not just the generic "reviewing…" beat — so a worker that
    # completed appears as a room_message sender during the run.
    room_senders = {d.get("sender") for n, d in events if n == "room_message"}
    assert "liability" in room_senders
    # The stream still completed cleanly through to `done` (no deadlock).
    assert any(n == "done" for n, _ in events)


def test_sim_run_emits_no_progress_events():
    """The SIM path's collaborate is instant/canned — it must NOT stream `progress`."""
    import asyncio

    async def _collect():
        out = []
        async for ev, data in server_app.run_job(
            "contract-audit", document="", budget_usd=0.20, requested_mode="sim"
        ):
            out.append((ev, data))
        return out

    loop = asyncio.new_event_loop()
    try:
        events = loop.run_until_complete(_collect())
    finally:
        loop.close()
    assert not [n for n, _ in events if n == "progress"]


class _NoopReporter:
    """A reporter that adds no claims (so only the seeded finding is graded)."""

    async def synthesize(self, contract, findings, room_context):
        from agent_exchange.audit.room_audit_types import ReportResult

        return ReportResult(summary="(no synthesis)", claims=())


def test_seeded_fabrication_table_is_false_to_the_samples():
    """The seeded clauses must NOT appear in the sample docs (else not a fabrication)."""
    from agent_exchange.workers.nda_specialists import SAMPLE_NDA

    msa = server_app.SAMPLE_MSA
    _, msa_claim = server_app._SEEDED_FABRICATION["contract-audit"]
    # The MSA only has clauses 1-8; the seeded "Clause 12" is absent.
    assert "12." not in msa.replace("twelve (12)", "")  # the only "12" is the cap period
    # The fabricated assertion's distinctive phrase is absent from the document.
    assert "in perpetuity" not in msa
    _, nda_claim = server_app._SEEDED_FABRICATION["nda-review"]
    assert "publicly disclose" not in SAMPLE_NDA.lower()
