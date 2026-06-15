"""Offline tests for `CrewAISpecialist` — the CrewAI + Featherless clause-audit worker.

No network. The seam is exercised two ways, both purely local:
  - an injected fake `BaseLLM` (so CrewAI's real `Agent`/`Task`/`Crew` build path runs
    without an HTTP-backed LLM), and
  - a monkeypatched `Crew.kickoff` returning a canned `CrewOutput`-like object, so the
    crew "runs" deterministically and we assert the result flows through the shared,
    fail-soft `parse_findings`.

What we prove: a well-formed JSON crew result becomes the right `Finding`s (tagged with
the worker name); garbage output fail-softs to `[]`; a raising crew fail-softs to `[]`;
and `CrewAISpecialist` conforms to the `Specialist` protocol.
"""

import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import asyncio

import pytest

# Keep CrewAI quiet/offline-friendly under test (telemetry/OTEL make no calls anyway,
# but disabling them avoids noise and any startup network attempt).
os.environ.setdefault("OTEL_SDK_DISABLED", "true")
os.environ.setdefault("CREWAI_DISABLE_TELEMETRY", "true")

from agent_exchange.workers.crewai_specialist import CrewAISpecialist
from agent_exchange.workers.finding import Finding, Specialist
from agent_exchange.workers.specialist import SPECIALISTS

crewai = pytest.importorskip("crewai", reason="crewai not installed (frameworks extra)")
from crewai import BaseLLM  # noqa: E402


# --------------------------------------------------------------------------- helpers


class _FakeLLM(BaseLLM):
    """A networkless CrewAI LLM: satisfies the `Agent.llm` type (a real `BaseLLM`
    subclass) without ever calling out. `_run_crew` never actually invokes `.call`
    because we monkeypatch `Crew.kickoff`, but `Agent` validation requires a real one."""

    def call(self, messages, **kwargs):  # pragma: no cover - kickoff is patched
        return "[]"


class _FakeCrewOutput:
    """Minimal stand-in for CrewAI's `CrewOutput` — only `.raw` is read by the worker."""

    def __init__(self, raw: str) -> None:
        self.raw = raw


# The (name, area, system_prompt) liability triple — reused so the agent is built from
# the SAME prompt the native worker uses.
_LIAB_NAME, _LIAB_AREA, _LIAB_PROMPT = SPECIALISTS[0]
assert _LIAB_NAME == "liability"

_GOOD_JSON = (
    '[{"clause_ref": "7.1", "claim": "Clause 7.1 caps Vendor liability at fees paid '
    'in the prior 12 months", "severity": "high"}, '
    '{"clause_ref": "7.2", "claim": "Clause 7.2 excludes consequential damages for '
    'both parties", "severity": "medium"}]'
)


def _make_specialist() -> CrewAISpecialist:
    return CrewAISpecialist(
        name=_LIAB_NAME, area=_LIAB_AREA, system_prompt=_LIAB_PROMPT, llm=_FakeLLM(model="fake-1")
    )


# --------------------------------------------------------------------------- tests


def test_protocol_conformance() -> None:
    """CrewAISpecialist satisfies the runtime-checkable Specialist protocol."""
    spec = _make_specialist()
    assert isinstance(spec, Specialist)
    assert spec.name == "liability"


def test_findings_parses_good_json(monkeypatch) -> None:
    """A well-formed JSON crew result → the right Findings via the shared parser."""
    captured = {}

    def fake_kickoff(self, *args, **kwargs):
        # Confirm the contract actually reached the task description (prompt reuse path).
        captured["task_desc"] = self.tasks[0].description
        return _FakeCrewOutput(_GOOD_JSON)

    monkeypatch.setattr(crewai.Crew, "kickoff", fake_kickoff)

    spec = _make_specialist()
    findings = asyncio.run(spec.findings("SAMPLE CONTRACT: clause 7.1 ..."))

    assert "SAMPLE CONTRACT" in captured["task_desc"]  # contract flowed into the crew
    assert len(findings) == 2
    assert all(isinstance(f, Finding) for f in findings)
    assert all(f.worker == "liability" for f in findings)  # tagged with worker name
    assert findings[0].clause_ref == "7.1"
    assert findings[0].severity == "high"
    assert findings[1].severity == "medium"


def test_findings_failsoft_on_garbage(monkeypatch) -> None:
    """Non-JSON crew output → [] (fail-soft; nothing payable), never a raise."""
    monkeypatch.setattr(
        crewai.Crew, "kickoff", lambda self, *a, **k: _FakeCrewOutput("I could not find anything useful.")
    )
    spec = _make_specialist()
    assert asyncio.run(spec.findings("contract")) == []


def test_findings_failsoft_on_crew_exception(monkeypatch) -> None:
    """A raising crew/LLM → [] (fail-soft); a flaky CrewAI worker never crashes the pool."""

    def boom(self, *a, **k):
        raise RuntimeError("featherless exploded")

    monkeypatch.setattr(crewai.Crew, "kickoff", boom)
    spec = _make_specialist()
    assert asyncio.run(spec.findings("contract")) == []


def test_findings_strips_markdown_fences(monkeypatch) -> None:
    """parse_findings reuse: fenced JSON is still parsed (shared fail-soft parser)."""
    fenced = "```json\n" + _GOOD_JSON + "\n```"
    monkeypatch.setattr(crewai.Crew, "kickoff", lambda self, *a, **k: _FakeCrewOutput(fenced))
    spec = _make_specialist()
    findings = asyncio.run(spec.findings("contract"))
    assert len(findings) == 2
    assert findings[0].clause_ref == "7.1"


def test_uses_raw_attr_then_str_fallback(monkeypatch) -> None:
    """Result extraction prefers CrewOutput.raw; falls back to str() when raw is absent."""

    class _NoRaw:
        def __str__(self) -> str:
            return _GOOD_JSON

    monkeypatch.setattr(crewai.Crew, "kickoff", lambda self, *a, **k: _NoRaw())
    spec = _make_specialist()
    assert len(asyncio.run(spec.findings("contract"))) == 2
