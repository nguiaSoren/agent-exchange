"""Worker-pool tests — all offline (fake specialists, zero network).

Two halves:
  1. `parse_findings` — the robust JSON→Finding parser (happy / fenced / garbage /
     empty-claim skip / severity coercion). A junk worker produces no payable findings.
  2. `AuditPool` — concurrent fan-out over fake specialists implementing the
     `Specialist` protocol. A specialist that RAISES is contained (no crash, its
     findings drop to [], the failure lands on `.errors`), and aggregation order is
     DETERMINISTIC (sorted by specialist `.name`).
"""

from __future__ import annotations

import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from agent_exchange.workers.finding import Finding, parse_findings
from agent_exchange.workers.pool import AuditPool

CONTRACT = "7.1 Vendor's aggregate liability shall not exceed the fees paid in the prior 12 months."


# ── parse_findings ──

def test_parse_findings_valid_json_array():
    text = json.dumps([
        {"clause_ref": "7.1", "claim": "liability is capped at 12 months' fees", "severity": "high"},
        {"clause_ref": "9", "claim": "indemnity is mutual", "severity": "low"},
    ])
    out = parse_findings(text, worker="liability-bot")
    assert len(out) == 2
    assert all(isinstance(f, Finding) for f in out)
    assert out[0].worker == "liability-bot"          # worker stamped from the arg, not the JSON
    assert out[0].clause_ref == "7.1" and out[0].claim == "liability is capped at 12 months' fees"
    assert out[0].severity == "high" and out[1].severity == "low"


def test_parse_findings_fenced_json():
    text = "```json\n" + json.dumps([{"clause_ref": "3", "claim": "termination needs 30 days' notice"}]) + "\n```"
    out = parse_findings(text, worker="termination-bot")
    assert len(out) == 1
    assert out[0].claim == "termination needs 30 days' notice"
    assert out[0].severity == "medium"               # absent severity → default medium


def test_parse_findings_garbage_returns_empty():
    # No JSON array at all → [] (fail-soft: a junk worker has nothing to pay for).
    assert parse_findings("the model rambled and produced no JSON", worker="w") == []
    assert parse_findings("", worker="w") == []
    # A malformed array (not valid JSON) also fails soft to [].
    assert parse_findings("[ {not valid json } ]", worker="w") == []
    # Top-level JSON that isn't a list → [].
    assert parse_findings('{"claim": "x"}', worker="w") == []


def test_parse_findings_skips_empty_or_missing_claim():
    text = json.dumps([
        {"clause_ref": "1", "claim": "real claim that stays"},
        {"clause_ref": "2", "claim": "   "},              # whitespace-only claim → skipped
        {"clause_ref": "3", "severity": "high"},          # missing claim → skipped
        {"clause_ref": "4"},                              # missing claim → skipped
        "not a dict",                                      # non-dict item → skipped
    ])
    out = parse_findings(text, worker="w")
    assert len(out) == 1
    assert out[0].claim == "real claim that stays"


def test_parse_findings_severity_coercion():
    text = json.dumps([
        {"claim": "a", "severity": "HIGH"},        # uppercase → "high"
        {"claim": "b", "severity": "Low"},          # mixed case → "low"
        {"claim": "c", "severity": "critical"},     # unknown → "medium"
        {"claim": "d", "severity": "med"},          # near-miss not low/high → "medium"
        {"claim": "e"},                             # absent → "medium"
        {"claim": "f", "severity": "hi"},           # "hi" prefix → "high"
    ])
    out = parse_findings(text, worker="w")
    assert [f.severity for f in out] == ["high", "low", "medium", "medium", "medium", "high"]


# ── fake specialists (implement the Specialist protocol) ──

class _FakeSpecialist:
    """A canned-findings specialist: `name` + async `findings(contract)`."""

    def __init__(self, name: str, findings: list[Finding]) -> None:
        self.name = name
        self._findings = findings

    async def findings(self, contract: str) -> list[Finding]:
        return list(self._findings)


class _RaisingSpecialist:
    """A specialist that blows up inside `findings` — must be contained by the pool."""

    def __init__(self, name: str) -> None:
        self.name = name

    async def findings(self, contract: str) -> list[Finding]:
        raise RuntimeError("simulated specialist failure")


def test_pool_aggregates_findings():
    a = _FakeSpecialist("alpha", [Finding("alpha", "1", "claim a1"), Finding("alpha", "2", "claim a2")])
    b = _FakeSpecialist("beta", [Finding("beta", "3", "claim b1")])
    pool = AuditPool([a, b])
    out = asyncio.run(pool.run(CONTRACT))
    assert [f.claim for f in out] == ["claim a1", "claim a2", "claim b1"]
    assert pool.errors == []


def test_pool_deterministic_order_sorted_by_name():
    # Register out of name order; expect the aggregate sorted by specialist name.
    z = _FakeSpecialist("zulu", [Finding("zulu", "9", "z claim")])
    a = _FakeSpecialist("alpha", [Finding("alpha", "1", "a claim")])
    m = _FakeSpecialist("mike", [Finding("mike", "5", "m claim")])
    pool = AuditPool([z, a, m])
    out = asyncio.run(pool.run(CONTRACT))
    assert [f.worker for f in out] == ["alpha", "mike", "zulu"]
    assert [f.claim for f in out] == ["a claim", "m claim", "z claim"]


def test_pool_contains_raising_specialist():
    good_a = _FakeSpecialist("alpha", [Finding("alpha", "1", "alpha claim")])
    bad = _RaisingSpecialist("bravo")
    good_c = _FakeSpecialist("charlie", [Finding("charlie", "2", "charlie claim")])
    pool = AuditPool([good_a, bad, good_c])
    out = asyncio.run(pool.run(CONTRACT))
    # The pool did NOT crash; it returns the surviving specialists' findings.
    assert [f.worker for f in out] == ["alpha", "charlie"]
    assert [f.claim for f in out] == ["alpha claim", "charlie claim"]
    # The failure is recorded (never silently swallowed), keyed by the raising worker.
    assert len(pool.errors) == 1
    name, err = pool.errors[0]
    assert name == "bravo"
    assert "RuntimeError" in err and "simulated specialist failure" in err


def test_pool_errors_reset_per_run():
    bad = _RaisingSpecialist("bravo")
    pool = AuditPool([bad])
    asyncio.run(pool.run(CONTRACT))
    assert len(pool.errors) == 1
    # A second run starts from a clean error slate (errors are per-run, not cumulative).
    asyncio.run(pool.run(CONTRACT))
    assert len(pool.errors) == 1


def test_pool_empty_roster_is_noop():
    pool = AuditPool([])
    assert asyncio.run(pool.run(CONTRACT)) == []
    assert pool.errors == []


def _run_all():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"  ✓ {fn.__name__}")
    print(f"\n{len(fns)} passed")


if __name__ == "__main__":
    _run_all()
