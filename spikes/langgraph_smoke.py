"""LIVE smoke (L3): a REAL LangGraphSpecialist on AI/ML API auditing a sample contract.

Exercises the live seam end-to-end — the LangGraph graph drives a real `ChatOpenAI`
pointed at AI/ML API, and we print the parsed findings. Run:

    ./.venv/bin/python spikes/langgraph_smoke.py

Requires `AIMLAPI_API_KEY` (+ optionally `AIMLAPI_MODEL`) in `.env`.
"""

from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from dotenv import load_dotenv

from agent_exchange.workers.langgraph_specialist import LangGraphSpecialist
from agent_exchange.workers.specialist import SPECIALISTS

# A short, concrete MSA snippet with a clear, one-sided liability term to find.
_SAMPLE_CONTRACT = """\
MASTER SERVICES AGREEMENT (excerpt)

7. LIMITATION OF LIABILITY.
7.1 Vendor's aggregate liability under this Agreement shall not exceed the total fees
    paid by Customer to Vendor in the three (3) months immediately preceding the event
    giving rise to the claim.
7.2 IN NO EVENT shall Vendor be liable for any indirect, incidental, consequential,
    special, or punitive damages, or for lost profits or lost data, even if advised of
    the possibility of such damages.
7.3 The limitations in this Section 7 shall NOT apply to Customer's payment obligations.
    (No carve-out is stated for Vendor's breach of confidentiality or IP infringement.)
"""


async def _main() -> int:
    load_dotenv()
    if not os.environ.get("AIMLAPI_API_KEY", "").strip():
        print("AIMLAPI_API_KEY not set — cannot run live smoke", file=sys.stderr)
        return 1

    name, area, system_prompt = SPECIALISTS[0]  # liability
    print(f"model: {os.environ.get('AIMLAPI_MODEL', '<default>')}  worker: {name}")
    spec = LangGraphSpecialist(name=name, area=area, system_prompt=system_prompt)

    findings = await spec.findings(_SAMPLE_CONTRACT)
    print(f"\n{len(findings)} finding(s) from AI/ML API via LangGraph:\n")
    for i, f in enumerate(findings, 1):
        print(f"  {i}. [{f.severity}] clause {f.clause_ref or '-'}: {f.claim}")
    return 0 if findings else 2


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
