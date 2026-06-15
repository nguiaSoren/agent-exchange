"""Audit-pipeline live smoke — the FULL marketplace flow on real models, end to end.

Fans a roster of real audit specialists (AuditPool) over a realistic MSA, grades every
finding against the contract on a live verifier model (Verifier), and settles under the
default policy — printing, grouped by worker, each finding + its verdict + confidence,
then the settlement ruling. This is the live counterpart to the offline proof already
green in tests/test_audit_pipeline.py ("seeded liar caught + not paid", no network).

Needs OPENAI_API_KEY (specialists) + AIMLAPI_API_KEY (verifier) in .env, plus
optionally OPENAI_AUDIT_MODEL / AIMLAPI_VERIFIER_MODEL to override the defaults.

Run: cd agent-exchange && .venv/bin/python spikes/audit_smoke.py
"""

from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import httpx
from dotenv import load_dotenv

from agent_exchange.audit.pipeline import audit
from agent_exchange.core import make_backend
from agent_exchange.metrics import usdc
from agent_exchange.verify import Verifier
from agent_exchange.workers.pool import AuditPool
from agent_exchange.workers.specialist import make_pool_specialists

# Explicit path (load_dotenv() with no path can fail depending on cwd).
load_dotenv("/Users/soren/Desktop/BAND HACKATHON/agent-exchange/.env")

# A realistic ~8-clause MSA: liability cap, IP, termination/notice, confidentiality/data,
# indemnity — enough surface that multiple specialists each find something.
CONTRACT = """
MASTER SERVICES AGREEMENT

1. Services. Vendor shall provide the data-integration services described in each Order Form.

2. Fees. Customer shall pay all undisputed fees within thirty (30) days of invoice.

3. Limitation of Liability. Vendor's aggregate liability under this Agreement shall not
   exceed the total fees paid by Customer in the twelve (12) months preceding the event
   giving rise to the claim. Neither party is liable for indirect, incidental, or
   consequential damages.

4. Intellectual Property. All pre-existing materials remain the property of their owner.
   Customer is granted a non-exclusive, non-transferable license to use the Deliverables
   solely for its internal business purposes. Vendor retains ownership of all underlying
   tools, libraries, and know-how.

5. Term and Termination. This Agreement commences on the Effective Date and continues for
   one (1) year, renewing automatically for successive one-year terms unless either party
   gives sixty (60) days' written notice of non-renewal. Either party may terminate for
   material breach that remains uncured thirty (30) days after written notice.

6. Confidentiality. Each party shall protect the other's Confidential Information using at
   least the same care it uses for its own, and shall not disclose it for three (3) years
   after termination.

7. Data Protection. Vendor shall process Customer Personal Data only on documented
   instructions, implement appropriate technical and organizational measures, and notify
   Customer of a personal-data breach without undue delay and in any event within 72 hours.

8. Indemnification. Vendor shall indemnify Customer against third-party claims arising from
   Vendor's infringement of intellectual-property rights, subject to the limitation of
   liability in Section 3.
""".strip()


def _verdict_mark(v: str) -> str:
    return {"confirmed": "✅", "partial": "🟡", "unsupported": "❌"}.get(v, "❔")


async def main() -> None:
    audit_model = os.getenv("OPENAI_AUDIT_MODEL", "gpt-4.1-mini")
    verifier_model = os.getenv("AIMLAPI_VERIFIER_MODEL", "gpt-5.1-2025-11-13")

    if not os.environ.get("OPENAI_API_KEY", "").strip():
        print("OPENAI_API_KEY not set — add it to .env to run the live specialists.")
        return
    if not os.environ.get("AIMLAPI_API_KEY", "").strip():
        print("AIMLAPI_API_KEY not set — add it to .env to run the live verifier.")
        return

    pool = AuditPool(make_pool_specialists("openai", audit_model))
    verifier = Verifier(make_backend("openai", verifier_model))
    print(f"specialists: {[s.name for s in pool.specialists]} on {audit_model}")
    print(f"verifier:    {verifier_model}\n")

    try:
        report = await audit(
            CONTRACT,
            contract_id="acme-msa",
            pool=pool,
            verifier=verifier,
            authorized_atomic=usdc(0.05),
        )
    except httpx.HTTPStatusError as e:
        code = e.response.status_code
        hint = {
            401: "key invalid",
            403: "key not active / no credits — try after your provider balance activates",
            404: "model id not found — check OPENAI_AUDIT_MODEL / AIMLAPI_VERIFIER_MODEL",
            429: "rate-limited — wait and retry",
        }.get(code, "see the response body")
        print(f"live call failed: HTTP {code} — {hint}.")
        print("(the pipeline logic itself is proven offline: tests/test_audit_pipeline.py is green.)")
        return

    if pool.errors:
        print(f"(note) {len(pool.errors)} specialist(s) errored and were contained:")
        for name, err in pool.errors:
            print(f"   ⚠ {name}: {err}")
        print()

    # Group the audited findings by the worker that produced them.
    by_worker: dict[str, list] = {}
    for af in report.audited:
        by_worker.setdefault(af.finding.worker, []).append(af)

    for worker in sorted(by_worker):
        print(f"── {worker} ──")
        for af in by_worker[worker]:
            f, v = af.finding, af.verdict
            ref = f.clause_ref or "—"
            print(f"  {_verdict_mark(v.verdict.value)} [{f.severity:6}] clause {ref}: {f.claim}")
            print(f"       → {v.verdict.value} (conf={v.confidence:.2f}) — {v.reason}")
        print()

    r = report.ruling
    print(
        f"settlement: pay_fraction={r.pay_fraction:.2f}  escalate={r.escalate}  "
        f"(confirmed={r.n_confirmed} partial={r.n_partial} unsupported={r.n_unsupported})"
    )
    print("→ unsupported (fabricated) findings earn $0 — you only pay for verified work.")


if __name__ == "__main__":
    asyncio.run(main())
