"""End-to-end audit-pipeline tests — the seeded-liar proof, proven OFFLINE.

`audit()` ties the whole flow together: fan specialists over a contract (AuditPool) →
grade every claim against the contract (Verifier on a MockBackend) → settle under a
policy (rule_settlement) → emit one AuditReport + (optionally) one immutable JobTrace.

The crafted scenario is the project's headline claim made concrete: a deliverable with
3 findings, one of them FABRICATED. The verifier returns `unsupported` for the lie and
`confirmed`/`partial` for the rest; under STRICT the fabricated finding earns $0. That
is "you only pay for verified work" — caught + not paid — with no live model in the loop.

Ordering contract (per finding.py + verifier.py + pool.py): the verifier returns
verdicts IN ORDER of the claims passed, and the pool sorts findings by specialist
`.name`. To keep claims-order == findings-order we use ONE specialist emitting all 3
findings in a known order, so the crafted MockBackend verdict array lines up 1:1.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from agent_exchange.audit.pipeline import audit
from agent_exchange.audit.report import AuditReport
from agent_exchange.core import MockBackend
from agent_exchange.metrics import TraceWriter, usdc
from agent_exchange.verify import STRICT, Verdict, Verifier
from agent_exchange.workers.finding import Finding
from agent_exchange.workers.pool import AuditPool

CONTRACT = """\
1. Liability. Vendor's aggregate liability shall not exceed the fees paid in the prior 12 months.
2. Termination. Either party may terminate for convenience on 30 days' written notice.
3. Confidentiality. Each party shall protect the other's confidential information for 3 years.
"""

# One specialist emits all three findings IN THIS ORDER, so claims order == findings order.
# Finding #2 is the SEEDED LIAR: clause 9.4 does not exist in the contract above.
FINDINGS = [
    Finding(worker="msa-bot", clause_ref="1", claim="liability is capped at the prior 12 months' fees", severity="high"),
    Finding(worker="msa-bot", clause_ref="9.4", claim="clause 9.4 grants the vendor unlimited indemnity", severity="high"),
    Finding(worker="msa-bot", clause_ref="2", claim="either party may terminate for convenience on 30 days' notice", severity="medium"),
]

# The crafted verifier reply, one object per claim IN ORDER:
#   #1 confirmed (real, full credit), #2 unsupported (the fabricated clause — $0),
#   #3 partial (mechanism right; under STRICT a partial also earns $0).
VERIFIER_REPLY = json.dumps([
    {"verdict": "confirmed", "confidence": 0.96, "reason": "matches clause 1", "evidence_quote": "Vendor's aggregate liability shall not exceed the fees paid in the prior 12 months."},
    {"verdict": "unsupported", "confidence": 0.93, "reason": "clause 9.4 is absent — fabricated", "evidence_quote": None},
    {"verdict": "partial", "confidence": 0.88, "reason": "termination is supported but only for convenience", "evidence_quote": "Either party may terminate for convenience on 30 days' written notice."},
])


class _MsaSpecialist:
    """A single fake specialist that emits the three crafted findings, in order."""

    name = "msa-bot"

    async def findings(self, contract: str) -> list[Finding]:
        return list(FINDINGS)


def _build():
    pool = AuditPool([_MsaSpecialist()])
    verifier = Verifier(MockBackend(reply=VERIFIER_REPLY))
    return pool, verifier


def _audit(writer=None) -> AuditReport:
    pool, verifier = _build()
    return asyncio.run(
        audit(
            CONTRACT,
            contract_id="acme-msa",
            pool=pool,
            verifier=verifier,
            policy=STRICT,
            authorized_atomic=usdc(0.05),
            writer=writer,
        )
    )


# ── report summary props ──

def test_report_summary_props():
    report = _audit()
    assert isinstance(report, AuditReport)
    assert report.contract_id == "acme-msa"
    assert report.n_findings == 3
    assert report.n_high_risk == 2                 # the two "high" findings
    assert report.n_confirmed == 1                 # only finding #1
    assert report.n_unsupported == 1               # the fabricated finding #2
    # findings + verdicts stay aligned 1:1, in the crafted order
    assert [af.finding.clause_ref for af in report.audited] == ["1", "9.4", "2"]
    assert [af.verdict.verdict for af in report.audited] == [Verdict.CONFIRMED, Verdict.UNSUPPORTED, Verdict.PARTIAL]


# ── the seeded liar earns $0 under STRICT ──

def test_seeded_liar_caught_and_not_fully_paid_under_strict():
    report = _audit()
    ruling = report.ruling
    # The lie was caught and (under STRICT) so was the partial: only 1 of 3 fully confirmed.
    assert ruling.n_unsupported == 1
    assert ruling.n_confirmed == 1
    assert ruling.n_partial == 1
    assert ruling.policy == "strict"
    # STRICT: confirmed=1, partial=0, unsupported=0 → pay_fraction = (1 + 0 + 0) / 3.
    assert abs(ruling.pay_fraction - (1.0 / 3.0)) < 1e-9
    assert ruling.escalate is False                # all three verdicts are high-confidence
    assert ruling.all_clean is False               # a fabricated claim was present


# ── the trace: exactly one immutable JobTrace row, readable back ──

def test_audit_writes_one_jobtrace_row():
    with tempfile.TemporaryDirectory() as d:
        writer = TraceWriter(os.path.join(d, "traces.jsonl"))
        report = _audit(writer=writer)
        rows = writer.read_all()
        assert len(rows) == 1                       # exactly one JobTrace per audit
        row = rows[0]
        # The row carries the headline-metric inputs and stays consistent with the report.
        assert row["job_id"] == report.contract_id == "acme-msa"
        assert len(row["claims"]) == report.n_findings == 3
        assert sum(1 for c in row["claims"] if c["verdict"] == "unsupported") == 1
        # Money invariant: authorized − settled == withheld, and the lie kept money back.
        assert row["amount_withheld_atomic"] == row["amount_authorized_atomic"] - row["amount_settled_atomic"]
        assert row["amount_settled_atomic"] < row["amount_authorized_atomic"]


def _run_all():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"  ✓ {fn.__name__}")
    print(f"\n{len(fns)} passed")


if __name__ == "__main__":
    _run_all()
