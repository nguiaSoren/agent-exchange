"""Offline tests for `LangGraphSpecialist` — the cross-framework (LangGraph) worker.

No network: a fake LangChain chat model is injected at the constructor boundary, so
the REAL LangGraph graph (StateGraph → compile → ainvoke) runs end-to-end against a
canned completion. We assert: (1) a well-formed JSON completion is parsed into the
right `Finding` objects via the shared `parse_findings`; (2) garbage output is
fail-soft → `[]`; (3) the worker conforms to the `Specialist` protocol; (4) the
roster factory builds one worker per roster entry.
"""

import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import asyncio

from langchain_core.language_models.fake_chat_models import FakeListChatModel

from agent_exchange.workers.finding import Finding, Specialist
from agent_exchange.workers.langgraph_specialist import (
    LangGraphSpecialist,
    langgraph_roster_for,
)
from agent_exchange.workers.specialist import SPECIALISTS

# A canned, well-formed findings array (exactly the JSON shape `parse_findings` consumes).
_GOOD_JSON = """[
  {"clause_ref": "7.1", "claim": "Clause 7.1 caps Vendor's liability at fees paid in the prior 12 months", "severity": "high"},
  {"clause_ref": "", "claim": "No carve-out for breach of confidentiality from the liability cap", "severity": "medium"}
]"""


def _specialist(reply: str) -> LangGraphSpecialist:
    """A LangGraphSpecialist whose graph is driven by a fake chat model returning `reply`."""
    name, area, system_prompt = SPECIALISTS[0]  # the liability prompt
    fake = FakeListChatModel(responses=[reply])
    return LangGraphSpecialist(name=name, area=area, system_prompt=system_prompt, llm=fake)


def test_findings_parses_good_output_into_findings():
    spec = _specialist(_GOOD_JSON)
    out = asyncio.run(spec.findings("SAMPLE CONTRACT TEXT"))
    assert len(out) == 2
    assert all(isinstance(f, Finding) for f in out)
    # Every finding is attributed to this worker (so it is payable to the right worker).
    assert all(f.worker == "liability" for f in out)
    assert out[0].clause_ref == "7.1"
    assert out[0].severity == "high"
    assert "caps Vendor's liability" in out[0].claim
    assert out[1].clause_ref == ""
    assert out[1].severity == "medium"


def test_findings_failsoft_on_garbage_output():
    spec = _specialist("this is not JSON at all, just prose — no array here")
    out = asyncio.run(spec.findings("SAMPLE CONTRACT TEXT"))
    assert out == []  # fail-soft: nothing to verify, nothing to pay


def test_findings_failsoft_on_empty_array():
    spec = _specialist("[]")
    out = asyncio.run(spec.findings("SAMPLE CONTRACT TEXT"))
    assert out == []


def test_findings_failsoft_on_malformed_json():
    # Has brackets (so the parser attempts json.loads) but is not valid JSON.
    spec = _specialist('[{"claim": "missing closing brace" ')
    out = asyncio.run(spec.findings("SAMPLE CONTRACT TEXT"))
    assert out == []


def test_findings_runs_through_real_langgraph_graph():
    # Sanity: the worker actually compiles + drives a LangGraph graph (not a bare call).
    spec = _specialist(_GOOD_JSON)
    asyncio.run(spec.findings("SAMPLE"))
    from langgraph.graph.state import CompiledStateGraph

    assert isinstance(spec._graph, CompiledStateGraph)


def test_conforms_to_specialist_protocol():
    spec = _specialist(_GOOD_JSON)
    assert isinstance(spec, Specialist)


def test_langgraph_roster_for_builds_full_roster():
    roster = langgraph_roster_for("contract-audit")
    assert len(roster) == len(SPECIALISTS)
    assert all(isinstance(s, LangGraphSpecialist) for s in roster)
    assert [s.name for s in roster] == [name for name, _, _ in SPECIALISTS]


def test_langgraph_roster_for_unknown_kind_raises():
    import pytest

    with pytest.raises(ValueError):
        langgraph_roster_for("no-such-kind")
