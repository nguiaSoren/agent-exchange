"""Job-type registry + NDA-review parity tests — all OFFLINE (MockBackend, no network).

The marketplace now handles a SECOND job type (NDA review) at FULL PARITY with the
original contract audit: its own document-generic verifier routing, its own specialist
roster, and its own hand-labeled calibration gold. These tests prove the routing without
spending — that the SAME mechanism (registry → roster → verifier → calibration) carries a
new document type with only data, not new machinery.

Covers:
  - the job-type registry: `job_kinds()`, `document_label_for(kind)`, `roster_for(...)`
    builds a full roster, and an unknown kind raises;
  - `Job` backward-compat: the default kind is the contract audit; an explicit NDA kind
    sticks;
  - the NDA verifier path: a `Verifier(..., document_label="NDA")` routes "NDA" into both
    the system + user prompt (inspected on a recording backend), and grades a known claim;
  - the NDA calibration gold loads with the right labels (unsupported → FABRICATED,
    confirmed/partial → GENUINE).

Run:  PYTHONHASHSEED=1 .venv/bin/python tests/test_job_types.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from agent_exchange.core import CompletionResult, Message, MockBackend, Usage
from agent_exchange.core.backend import ModelBackend
from agent_exchange.eval.seeded_liar import gold_claims_from_calibration
from agent_exchange.eval.types import FABRICATED, GENUINE, LabeledClaim
from agent_exchange.market.schema import Job
from agent_exchange.verify import Verdict, Verifier
from agent_exchange.workers.job_types import (
    document_label_for,
    job_kinds,
    roster_for,
)

_NDA_CASES = os.path.join(
    os.path.dirname(__file__), "..", "data", "calibration", "nda_cases.json"
)

_CONTRACT = "contract-audit"
_NDA = "nda-review"


# ── a backend that RECORDS the messages it was handed (to inspect prompt routing) ──

class _RecordingBackend(ModelBackend):
    """Returns one fixed JSON reply, and stashes the messages of the last call so a test
    can assert what the verifier put into the system/user turn (mirrors how
    test_verifier inspects the prompt indirectly). `reply` defaults to a single-claim
    confirmed verdict."""

    provider: str = "mock"
    model: str = "recording-1"

    def __init__(self, reply: str | None = None):
        self.reply = reply or json.dumps(
            [{"verdict": "confirmed", "confidence": 0.9, "reason": "matches", "evidence_quote": "x"}]
        )
        self.last_messages: list[Message] = []

    async def complete(
        self,
        messages: list[Message],
        *,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> CompletionResult:
        self.last_messages = list(messages)
        usage = Usage(1, 1, 2, estimated_cost_usd=0.0)
        return CompletionResult(
            text=self.reply,
            model=self.model,
            provider=self.provider,
            usage=usage,
            submission_ns=0,
            return_ns=1,
            finish_reason="stop",
        )


# ── the registry ──

def test_job_kinds_includes_both_types():
    kinds = job_kinds()
    assert _CONTRACT in kinds
    assert _NDA in kinds


def test_document_label_for_each_kind():
    assert document_label_for(_NDA) == "NDA"
    assert document_label_for(_CONTRACT) == "contract"


def test_roster_for_nda_builds_six_workers():
    # `roster_for` constructs a backend (never calls it here) — `make_backend` needs a
    # key present, so set a dummy one. No network: building the roster never spends.
    os.environ.setdefault("OPENAI_API_KEY", "test-dummy-key")
    roster = roster_for(_NDA, "openai", "gpt-4.1-mini")
    assert len(roster) == 6
    # each worker carries a unique name (so findings are attributable/payable)
    names = [w.name for w in roster]
    assert len(set(names)) == 6


def test_roster_for_unknown_kind_raises():
    # the unknown-kind check happens before any backend wiring, so no key is needed.
    try:
        roster_for("does-not-exist", "openai", "gpt-4.1-mini")
        raise AssertionError("unknown kind must raise")
    except (KeyError, ValueError):
        pass


# ── Job backward-compat ──

def test_job_defaults_to_contract_audit():
    job = Job(job_id="x", contract="some contract text", budget_atomic=1)
    assert job.kind == _CONTRACT


def test_job_explicit_nda_kind_sticks():
    job = Job(job_id="x", contract="some NDA text", budget_atomic=1, kind=_NDA)
    assert job.kind == _NDA


# ── the NDA verifier path ──

def test_nda_verifier_routes_nda_into_the_prompt():
    """A Verifier built with document_label='NDA' must put 'NDA' into the system prompt
    (mirroring how test_verifier inspects the verifier's messages)."""
    backend = _RecordingBackend()
    verifier = Verifier(backend, document_label="NDA")
    claim = "Orally disclosed information can qualify as Confidential Information."
    contract = (
        '1. "Confidential Information" means all non-public information disclosed '
        "whether oral, written, or electronic."
    )
    verdicts = asyncio.run(verifier.verify(contract, [claim]))
    # routing: the document word reaches BOTH the system and the user turn.
    system_msg = backend.last_messages[0].content
    user_msg = backend.last_messages[-1].content
    assert "NDA" in system_msg
    assert "NDA" in user_msg
    # and the verifier still returns the backend's verdict, in order.
    assert len(verdicts) == 1
    assert verdicts[0].verdict is Verdict.CONFIRMED


def test_nda_verifier_grades_a_known_claim_via_plain_mock():
    """A single fixed-reply MockBackend drives a known NDA verdict (the simplest
    seeded-liar shape — one fabricated claim caught → unsupported)."""
    reply = json.dumps(
        [{"verdict": "unsupported", "confidence": 0.9, "reason": "absent from snippet", "evidence_quote": None}]
    )
    verifier = Verifier(MockBackend(reply=reply), document_label="NDA")
    contract = "3. The Receiving Party shall use the Confidential Information solely for the Purpose."
    claim = "The Receiving Party may use the Confidential Information to develop competing products."
    vs = asyncio.run(verifier.verify(contract, [claim]))
    assert vs[0].verdict is Verdict.UNSUPPORTED


# ── the NDA calibration gold ──

def test_nda_gold_loads_with_correct_labels():
    gold = gold_claims_from_calibration(_NDA_CASES)
    assert all(isinstance(g, LabeledClaim) for g in gold)
    # 22 cases, all mappable (gold ∈ confirmed/partial/unsupported).
    assert len(gold) == 22
    n_fab = sum(g.label == FABRICATED for g in gold)
    n_gen = sum(g.label == GENUINE for g in gold)
    # gold='unsupported' → FABRICATED; gold ∈ {confirmed, partial} → GENUINE.
    assert n_fab == 10 and n_gen == 12
    assert n_fab + n_gen == len(gold)
    # spot-checks tying a known case to its label.
    # nda02 (oral excluded by a writing-only definition) → unsupported → FABRICATED
    nda02 = next(g for g in gold if "disclosed orally is covered" in g.claim.lower())
    assert nda02.label == FABRICATED
    # nda01 (oral can qualify) → confirmed → GENUINE
    nda01 = next(g for g in gold if g.claim == "Orally disclosed information can qualify as Confidential Information.")
    assert nda01.label == GENUINE
    # nda06 (drops the 'no fault' qualifier) → partial → GENUINE (grounded, not invented)
    nda06 = next(g for g in gold if g.claim == "Publicly available information is excluded from the confidentiality obligations.")
    assert nda06.label == GENUINE
    # every claim carries the calibration provenance.
    assert all(g.source for g in gold)
    print(f"    nda gold: {n_fab} fabricated / {n_gen} genuine")


def _run_all():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"  ✓ {fn.__name__}")
    print(f"\n{len(fns)} passed")


if __name__ == "__main__":
    _run_all()
