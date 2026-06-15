"""Offline tests for POST /api/audit — the verify-only "paste your own contract" route.

All offline: a fixed-reply `MockBackend` stands in for the workers, and sim.py's
content-keyed `KeyedVerifierBackend` stands in for the verifier, so NO network is hit.
We drive the real route via FastAPI's `TestClient`, monkeypatching the two backend
factories the endpoint uses (`make_backend` for the verifier, and `_run_audit`'s
injectable backends) so the locked response contract is exercised end-to-end.

Coverage:
  * a normal audit returns findings + verdicts in the locked shape (gate_passed True);
  * a seeded fabricated claim -> unsupported + gate_passed False + a catch summary;
  * an oversize document -> 413;
  * the daily budget cap -> 429 once exceeded;
  * an unknown kind -> 422.
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

import app as server_app
import demo_budget
from agent_exchange.core.backend import MockBackend
from sim import KeyedVerifierBackend

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

# The single claim every mocked specialist emits (all 6 share one fixed-reply backend).
_CLAIM = "Vendor's aggregate liability is capped at the fees paid in the prior 12 months."
_QUOTE = "Vendor's aggregate liability under this Agreement is capped at the fees paid by Client in the twelve (12) months preceding the claim."

_DOC = (
    "MASTER SERVICES AGREEMENT\n\n"
    "1. Liability. Vendor's aggregate liability under this Agreement is capped at the "
    "fees paid by Client in the twelve (12) months preceding the claim.\n"
)


def _worker_reply() -> str:
    """A worker completion: one finding, parsed by `parse_findings` into a Finding."""
    return json.dumps([{"clause_ref": "1", "claim": _CLAIM, "severity": "high"}])


def _install_backends(monkeypatch, *, verdict: str, evidence: str | None) -> None:
    """Patch the endpoint's backend seams so the run is fully offline + deterministic.

    The worker side: every `roster_for(...)` specialist gets a fixed-reply MockBackend
    (via patching `make_backend` to ignore provider/model and return the mock). The
    verifier side: a content-keyed mock that grades `_CLAIM` with the requested verdict.
    """
    worker_backend = MockBackend(reply=_worker_reply())
    verifier_backend = KeyedVerifierBackend({_CLAIM: (verdict, 0.95, evidence)})

    from agent_exchange.workers.job_types import JOB_TYPES
    from agent_exchange.workers.specialist import SpecialistWorker

    def fake_roster_for(kind, provider, model):
        # Build a real specialist on the offline mock worker backend (no network). We use
        # a SINGLE specialist so the 6 roster slots don't each re-emit the same fixed
        # mock finding (which would create 6 duplicate claims -> the content-keyed mock
        # verifier only grades the first, fail-safing the rest). One specialist == one
        # claim == a clean 1:1 finding/verdict pairing, which is what we assert on.
        n, a, p = JOB_TYPES[kind].specialists[0]
        return [SpecialistWorker(name=n, area=a, system_prompt=p, backend=worker_backend)]

    def fake_make_backend(provider, model, **kwargs):
        # The endpoint builds the verifier via make_backend; hand back the keyed mock.
        return verifier_backend

    monkeypatch.setattr(server_app, "roster_for", fake_roster_for)
    monkeypatch.setattr(server_app, "make_backend", fake_make_backend)


@pytest.fixture(autouse=True)
def _fresh_budget(monkeypatch):
    """Reset the process-global budget guard before each test (isolated daily counter)."""
    demo_budget.reset_demo_guard()
    yield
    demo_budget.reset_demo_guard()


@pytest.fixture
def client() -> TestClient:
    return TestClient(server_app.app)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_normal_audit_returns_locked_shape(client, monkeypatch):
    _install_backends(monkeypatch, verdict="confirmed", evidence=_QUOTE)
    r = client.post("/api/audit", json={"kind": "contract-audit", "document_text": _DOC})
    assert r.status_code == 200, r.text
    body = r.json()

    # Locked keys present.
    for key in (
        "kind", "n_findings", "n_confirmed", "n_partial", "n_unsupported",
        "gate_passed", "catch_summary", "est_cost_usd", "findings",
    ):
        assert key in body, f"missing key {key!r} in {body}"

    assert body["kind"] == "contract-audit"
    assert body["n_findings"] >= 1
    assert body["n_findings"] == body["n_confirmed"]  # all confirmed in this run
    assert body["n_unsupported"] == 0
    assert body["gate_passed"] is True
    assert isinstance(body["est_cost_usd"], (int, float))

    f = body["findings"][0]
    for key in ("worker", "clause_ref", "claim", "verdict", "confidence", "evidence_quote"):
        assert key in f
    assert f["verdict"] == "confirmed"
    assert f["evidence_quote"] == _QUOTE


def test_seeded_fabrication_is_caught(client, monkeypatch):
    # A claim graded unsupported (no evidence) -> a fabrication catch.
    _install_backends(monkeypatch, verdict="unsupported", evidence=None)
    r = client.post("/api/audit", json={"kind": "contract-audit", "document_text": _DOC})
    assert r.status_code == 200, r.text
    body = r.json()

    assert body["n_unsupported"] >= 1
    assert body["gate_passed"] is False
    assert "fabricated" in body["catch_summary"].lower()
    assert all(f["verdict"] == "unsupported" for f in body["findings"])


def test_oversize_document_413(client, monkeypatch):
    _install_backends(monkeypatch, verdict="confirmed", evidence=_QUOTE)
    big = "x" * (server_app._AUDIT_MAX_DOC_CHARS + 1)
    r = client.post("/api/audit", json={"kind": "contract-audit", "document_text": big})
    assert r.status_code == 413, r.text
    assert r.json()["error"] == "document_too_large"


def test_budget_cap_429(client, monkeypatch):
    _install_backends(monkeypatch, verdict="confirmed", evidence=_QUOTE)
    # Pin the daily cap tiny and make every projection blow it on the SECOND call:
    # set the cap so the first reserve fits and the second does not. Easiest: cap = a
    # value just above one projection. We force a fixed projection via _estimate_audit_cost.
    monkeypatch.setattr(server_app, "_estimate_audit_cost", lambda *a, **k: 1.0)
    # Cap at $1.50: first reserve (1.0) OK, second (would total 2.0) over.
    guard_caps = demo_budget.BudgetCaps(daily_usd=Decimal("1.50"))
    monkeypatch.setattr(
        demo_budget, "_guard", demo_budget.BudgetGuard(caps=guard_caps)
    )

    r1 = client.post("/api/audit", json={"kind": "contract-audit", "document_text": _DOC})
    assert r1.status_code == 200, r1.text
    r2 = client.post("/api/audit", json={"kind": "contract-audit", "document_text": _DOC})
    assert r2.status_code == 429, r2.text
    assert r2.json()["error"] == "demo_budget_reached"


def test_bad_kind_422(client, monkeypatch):
    _install_backends(monkeypatch, verdict="confirmed", evidence=_QUOTE)
    r = client.post("/api/audit", json={"kind": "not-a-real-kind", "document_text": _DOC})
    assert r.status_code == 422, r.text
    assert r.json()["error"] == "unknown_kind"
