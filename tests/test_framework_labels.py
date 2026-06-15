"""Tests for the cross-framework worker LABELS carried on the pool + bid SSE events.

Covers:
  * the framework-map module (`workers.job_types`): the exact assignment per the
    locked contract (ip=langgraph, liability=crewai for contract-audit;
    confidentiality_scope=langgraph, permitted_use=crewai for nda-review), and
    `framework_for` returning ``"native"`` for unmapped specialties + unknown kinds;
  * the sim scenario's pool + bids carry the correct ``framework`` per the map for
    BOTH kinds (incl. the cross-owner slot -> native);
  * the sim event generator emits ``pool``/``bid`` payloads with the ``framework``
    field set per the map.
"""

import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
# The server package (app.py / sim.py) lives under ../server, not in src.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))

import asyncio

import pytest

from agent_exchange.workers.job_types import FRAMEWORK_BY_SPECIALTY, framework_for


# --- the map module ---------------------------------------------------------

def test_framework_map_exact_assignment():
    assert FRAMEWORK_BY_SPECIALTY["contract-audit"] == {
        "ip": "langgraph", "liability": "crewai"}
    assert FRAMEWORK_BY_SPECIALTY["nda-review"] == {
        "confidentiality_scope": "langgraph", "permitted_use": "crewai"}


@pytest.mark.parametrize("kind, specialty, expected", [
    ("contract-audit", "ip", "langgraph"),
    ("contract-audit", "liability", "crewai"),
    ("contract-audit", "termination", "native"),
    ("contract-audit", "tax", "native"),          # cross-owner -> native
    ("nda-review", "confidentiality_scope", "langgraph"),
    ("nda-review", "permitted_use", "crewai"),
    ("nda-review", "term_survival", "native"),
    ("nda-review", "carve_outs", "native"),        # cross-owner -> native
])
def test_framework_for_mapped(kind, specialty, expected):
    assert framework_for(kind, specialty) == expected


def test_framework_for_unmapped_defaults_native():
    assert framework_for("contract-audit", "does-not-exist") == "native"
    assert framework_for("unknown-kind", "ip") == "native"  # unknown kind -> native


# --- the sim scenario -------------------------------------------------------

_EXPECTED = {
    "contract-audit": {
        "liability": "crewai", "ip": "langgraph", "termination": "native",
        "tax": "native",
    },
    "nda-review": {
        "confidentiality_scope": "langgraph", "permitted_use": "crewai",
        "term_survival": "native", "carve_outs": "native",
    },
}


@pytest.mark.parametrize("kind", ["contract-audit", "nda-review"])
def test_sim_scenario_pool_and_bids_carry_framework(kind):
    from sim import build_sim_scenario

    scenario = build_sim_scenario(kind, document="")
    exp = _EXPECTED[kind]

    # Pool entries: framework present and correct (pool entries lack a specialty
    # key, but their id is "<specialty>-bot" in the sim scenarios).
    by_bid = {b["worker"]: b["framework"] for b in scenario.bids}
    assert set(by_bid) == set(exp)
    for specialty, fw in exp.items():
        assert by_bid[specialty] == fw, f"bid {specialty} framework"

    # Pool: every entry carries a framework, and the two mapped slots match.
    for agent in scenario.pool:
        assert "framework" in agent
    pool_by_id = {a["id"]: a["framework"] for a in scenario.pool}
    assert pool_by_id["ip-bot"] == "langgraph" if kind == "contract-audit" \
        else pool_by_id["confidentiality-bot"] == "langgraph"


@pytest.mark.parametrize("kind", ["contract-audit", "nda-review"])
def test_sim_event_generator_emits_framework(kind):
    from app import run_job

    async def _collect():
        out = []
        async for ev, data in run_job(kind, document="", budget_usd=0.20,
                                      requested_mode="sim"):
            out.append((ev, data))
        return out

    events = _collect_sync(_collect)
    exp = _EXPECTED[kind]

    pools = [d for n, d in events if n == "pool"]
    assert len(pools) == 1
    for agent in pools[0]["agents"]:
        assert agent["framework"] in {"native", "langgraph", "crewai"}

    bids = [d for n, d in events if n == "bid"]
    assert {b["worker"] for b in bids} == set(exp)
    for b in bids:
        assert b["framework"] == exp[b["worker"]], f"bid {b['worker']} framework"


def _collect_sync(coro_factory):
    """Run an async collector to completion (own loop, robust under pytest)."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro_factory())
    finally:
        loop.close()
