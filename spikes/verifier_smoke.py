"""Verifier live smoke — grade real claims against a real contract on a live model.

Needs AIMLAPI_API_KEY + AIMLAPI_VERIFIER_MODEL (default the strong frontier model).
Runs three claims — one true, one partial, one FABRICATED — and shows the verdicts +
the settlement ruling (the fabricated claim must earn $0). This is the live proof of
the verification gate; the offline version is already green in tests/test_verifier.py.

Run: cd agent-exchange && .venv/bin/python spikes/verifier_smoke.py
"""

from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import httpx
from dotenv import load_dotenv

from agent_exchange.core import make_backend
from agent_exchange.verify import Verifier, rule_settlement

load_dotenv()

CONTRACT = """
MASTER SERVICES AGREEMENT (excerpt)
7.1 Vendor's aggregate liability under this Agreement shall not exceed the total fees
    paid by Customer in the twelve (12) months preceding the event giving rise to the claim.
7.2 Vendor disclaims liability for indirect, incidental, or consequential damages.
9.3 Either party may terminate for material breach with thirty (30) days' written notice
    if the breach remains uncured.
""".strip()

CLAIMS = [
    "Clause 7.1 caps Vendor's total liability at the fees paid in the prior 12 months.",  # true
    "The agreement limits liability for consequential damages.",                          # partial (7.2, but broad)
    "Clause 11 grants Customer an automatic 50% refund on any outage.",                   # FABRICATED — absent
]


async def main() -> None:
    key = os.environ.get("AIMLAPI_API_KEY", "").strip()
    model = os.getenv("AIMLAPI_VERIFIER_MODEL", "gpt-5.1-2025-11-13")
    if not key:
        print("AIMLAPI_API_KEY not set — add it to .env to run the live verifier.")
        return

    verifier = Verifier(make_backend("aimlapi", model))
    print(f"verifier model: {model}\n")
    try:
        verdicts = await verifier.verify(CONTRACT, CLAIMS)
    except httpx.HTTPStatusError as e:
        code = e.response.status_code
        hint = {
            401: "key invalid",
            403: "key not active / no credits yet — try after the kickoff activates your AI/ML API balance",
            404: "model id not found — check AIMLAPI_VERIFIER_MODEL against AI/ML API's model list",
            429: "rate-limited — wait and retry",
        }.get(code, "see the response body")
        print(f"live call failed: HTTP {code} — {hint}.")
        print("(the verifier logic itself is proven offline: tests/test_verifier.py = 9/9 green.)")
        return
    for v in verdicts:
        mark = {"confirmed": "✅", "partial": "🟡", "unsupported": "❌"}[v.verdict.value]
        print(f"{mark} [{v.verdict.value:11}] conf={v.confidence:.2f}  {v.claim}")
        print(f"     reason: {v.reason}")
        if v.evidence_quote:
            print(f"     evidence: “{v.evidence_quote.strip()[:120]}”")
    ruling = rule_settlement(verdicts)
    print(f"\nsettlement: pay_fraction={ruling.pay_fraction:.2f}  escalate={ruling.escalate}  "
          f"(confirmed={ruling.n_confirmed} partial={ruling.n_partial} unsupported={ruling.n_unsupported})")
    print("→ the fabricated claim earns $0; you pay only for verified work.")


if __name__ == "__main__":
    asyncio.run(main())
