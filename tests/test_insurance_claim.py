"""Insurance-claim (Track 3) job-type tests — all OFFLINE (MockBackend, no network).

The marketplace now handles a THIRD, REGULATED job type: auditing an adjuster's payout
determination against the POLICY and the CLAIM. These tests prove the routing the SAME way
`test_job_types.py` proves the NDA path — that the existing registry → roster → verifier
machinery carries a new high-stakes document type with only data, not new machinery — plus
the one thing unique to Track 3: the multi-source `CrossSourceVerifier` showcase, wired
ISOLATED by kind so the single-document audit/settle path is untouched.

Covers:
  - the job-type registry now includes "insurance-claim" with its own label + 5-worker roster;
  - the kind's verifier path grades the seeded fabricated COVERAGE assertion → unsupported;
  - the sample policy expressly EXCLUDES flood (so a "flood is covered" claim is provably false);
  - the multi-source CrossSourceVerifier marks the fabricated flood-coverage claim
    UNCORROBORATED across the two sources (policy + claim), and a genuine policy claim
    SINGLE_SOURCE — the isolated Track-3 showcase, run over real machinery.

Run:  PYTHONHASHSEED=1 .venv/bin/python tests/test_insurance_claim.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from agent_exchange.core import MockBackend
from agent_exchange.verify import Verdict, Verifier
from agent_exchange.verify.cross_source_verifier import Corroboration, CrossSourceVerifier
from agent_exchange.workers.insurance_specialists import (
    INSURANCE_SPECIALISTS,
    SAMPLE_INSURANCE_CLAIM,
    SAMPLE_INSURANCE_POLICY,
)
from agent_exchange.workers.job_types import (
    document_label_for,
    framework_for,
    job_kinds,
    roster_for,
)

_INS = "insurance-claim"


# ── the registry ──

def test_job_kinds_includes_insurance():
    assert _INS in job_kinds()


def test_document_label_for_insurance():
    assert document_label_for(_INS) == "insurance claim file"


def test_roster_for_insurance_builds_five_unique_workers():
    os.environ.setdefault("OPENAI_API_KEY", "test-dummy-key")
    roster = roster_for(_INS, "openai", "gpt-4.1-mini")
    assert len(roster) == 5
    names = [w.name for w in roster]
    assert len(set(names)) == 5
    # the documented specialties are present.
    assert set(names) == {
        "coverage_scope", "exclusions", "limits_deductible",
        "claim_validity", "payout_calculation",
    }


def test_insurance_roster_registry_shape():
    # mirrors specialist.SPECIALISTS: 5 (name, area, system_prompt) triples, each a str.
    assert len(INSURANCE_SPECIALISTS) == 5
    for name, area, prompt in INSURANCE_SPECIALISTS:
        assert name and area and prompt and isinstance(prompt, str)


def test_insurance_framework_routing_has_three_framework_slots():
    # parity with the other kinds: one LangGraph + two CrewAI slots, rest native.
    fws = {n: framework_for(_INS, n) for n, _a, _p in INSURANCE_SPECIALISTS}
    assert fws["coverage_scope"] == "langgraph"
    assert fws["exclusions"] == "crewai"
    assert fws["limits_deductible"] == "crewai"
    assert fws["claim_validity"] == "native"
    assert fws["payout_calculation"] == "native"


# ── the sample documents ──

def test_policy_expressly_excludes_flood():
    # The seeded fabrication target: the policy does NOT cover flood, so a "flood is
    # covered" determination is provably false against this text.
    assert "FLOOD" in SAMPLE_INSURANCE_POLICY
    assert "do NOT cover" in SAMPLE_INSURANCE_POLICY
    # the claim's determination DOES (wrongly) pay the flood portion — the thing to catch.
    assert "overflowing creek" in SAMPLE_INSURANCE_CLAIM


# ── the verifier path (single-document, the audit/settle flow) ──

def test_insurance_verifier_grades_fabricated_coverage_unsupported():
    """The fabricated COVERAGE assertion is graded unsupported (catch → $0)."""
    reply = json.dumps(
        [{"verdict": "unsupported", "confidence": 0.93,
          "reason": "flood is an express exclusion", "evidence_quote": None}]
    )
    verifier = Verifier(MockBackend(reply=reply), document_label="insurance claim file")
    document = SAMPLE_INSURANCE_POLICY + "\n" + SAMPLE_INSURANCE_CLAIM
    claim = "The policy's insuring agreement covers flood and rising surface water."
    vs = asyncio.run(verifier.verify(document, [claim]))
    assert vs[0].verdict is Verdict.UNSUPPORTED


def test_insurance_verifier_routes_label_into_prompt():
    """The kind's document label reaches the verifier's prompt (document-generic routing)."""

    class _Rec(MockBackend):
        def __init__(self):
            super().__init__(reply='[{"verdict":"confirmed","confidence":0.9,"reason":"r","evidence_quote":"q"}]')
            self.last = []

        async def complete(self, messages, *, temperature=0.0, max_tokens=None):
            self.last = list(messages)
            return await super().complete(messages, temperature=temperature, max_tokens=max_tokens)

    backend = _Rec()
    verifier = Verifier(backend, document_label="insurance claim file")
    asyncio.run(verifier.verify(SAMPLE_INSURANCE_POLICY, ["windstorm is a covered peril"]))
    system_msg = backend.last[0].content
    assert "insurance claim file" in system_msg


# ── the multi-source showcase (CrossSourceVerifier, isolated by kind) ──

def _scripted_verifier(verdict: str, conf: float = 0.95) -> Verifier:
    return Verifier(MockBackend(
        reply=f'[{{"verdict":"{verdict}","confidence":{conf},"reason":"r","evidence_quote":null}}]'
    ))


def test_cross_source_fabricated_flood_is_uncorroborated():
    """The fabricated flood-coverage claim grounds in NEITHER source → UNCORROBORATED.

    Both sources return 'unsupported' for the fabricated claim, so neither corroborates it
    — exactly the multi-source signal the Track-3 showcase surfaces (n_confirming==0)."""
    csv = CrossSourceVerifier(_scripted_verifier("unsupported"))
    sources = [("policy", SAMPLE_INSURANCE_POLICY), ("claim", SAMPLE_INSURANCE_CLAIM)]
    claim = "The policy's insuring agreement covers the rising-water flood loss."
    out = asyncio.run(csv.verify_claims([claim], sources))
    assert len(out) == 1
    assert out[0].level is Corroboration.UNCORROBORATED
    assert out[0].n_confirming == 0


def test_cross_source_genuine_claim_corroborated_when_both_confirm():
    """A genuine claim both sources confirm → CORROBORATED (≥2 witnesses, no dissent)."""
    csv = CrossSourceVerifier(_scripted_verifier("confirmed"))
    sources = [("policy", SAMPLE_INSURANCE_POLICY), ("claim", SAMPLE_INSURANCE_CLAIM)]
    claim = "Wind-driven roof damage is a covered windstorm loss under the policy."
    out = asyncio.run(csv.verify_claims([claim], sources))
    assert out[0].level is Corroboration.CORROBORATED
    assert out[0].trustworthy


# ── the full sim lifecycle (the server orchestrator, isolated by kind) ──

def test_sim_run_catches_fabrication_and_emits_cross_source():
    """End-to-end sim run of the kind: the fabricated flood-coverage finding is caught
    (gate fails → $0), and the Track-3 cross_source showcase emits (additive, isolated)."""
    os.environ.setdefault("OPENAI_API_KEY", "test-dummy-key")
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))
    import app  # the FastAPI lifecycle emitter

    async def _drive():
        out = []
        async for ev, data in app.run_job(_INS, "", 0.2, "sim"):
            out.append((ev, data))
        return out

    events = asyncio.run(_drive())
    by: dict[str, list] = {}
    for ev, d in events:
        by.setdefault(ev, []).append(d)

    # the seeded fabricator (payout_calculation) is graded unsupported → caught.
    fab = [f for f in by["finding"] if f["worker"] == "payout_calculation"]
    assert fab and fab[0]["verdict"] == "unsupported"
    # the job-level gate fails → nothing settles ($0 withheld is the headline).
    done = by["done"][0]
    assert done["gate_passed"] is False
    assert done["total_settled_usd"] == 0.0
    # the multi-source showcase ran and flagged the flood-coverage claim as uncorroborated.
    cs = by.get("cross_source", [])
    assert cs, "Track-3 cross_source showcase must emit for insurance-claim"
    flood = [c for c in cs if "covers the rising-water flood" in c["claim"].lower()]
    assert flood and flood[0]["level"] == "uncorroborated"


def _run_all():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"  ✓ {fn.__name__}")
    print(f"\n{len(fns)} passed")


if __name__ == "__main__":
    _run_all()
