"""LIVE smoke (L3): THREE different agent frameworks auditing the SAME contract.

The "3 frameworks · 2 partner sponsors · 1 job" proof in one command — each worker
implements the same `Specialist.findings(contract)` seam but runs a DIFFERENT agent
framework on a DIFFERENT provider:

  * native  SpecialistWorker  -> OpenAI            (the baseline brain)
  * LangGraph  StateGraph     -> AI/ML API         (partner sponsor)
  * CrewAI     Agent/Task/Crew-> Featherless        (partner sponsor, open-weight)

All three get the SAME liability prompt + the SAME contract, so the output is an
apples-to-apples view of three frameworks doing one job. Each is guarded: a missing
key just skips that framework (so it runs "lightly" even with partial creds).

Run:  ./.venv/bin/python spikes/three_frameworks_smoke.py
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

# Keep CrewAI telemetry quiet for a clean smoke.
os.environ.setdefault("OTEL_SDK_DISABLED", "true")
os.environ.setdefault("CREWAI_DISABLE_TELEMETRY", "true")

from dotenv import load_dotenv

from agent_exchange.workers.specialist import SPECIALISTS

# A short, concrete MSA excerpt with clear, one-sided liability terms to find.
_CONTRACT = """\
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

_NAME, _AREA, _PROMPT = SPECIALISTS[0]  # the liability specialist — same brief for all three


def _hr() -> None:
    print("─" * 72)


async def _run(framework: str, provider: str, model: str, build) -> int:
    """Build one framework's specialist and print its findings. Returns finding count."""
    _hr()
    print(f"  {framework:<10} → {provider:<11} ({model})")
    _hr()
    try:
        spec = build()
        findings = await spec.findings(_CONTRACT)
    except Exception as exc:  # noqa: BLE001 — a smoke degrades, never crashes the others
        print(f"  ⚠  skipped: {type(exc).__name__}: {exc}\n")
        return 0
    if not findings:
        print("  (no findings parsed)\n")
        return 0
    for i, f in enumerate(findings, 1):
        print(f"  {i}. [{f.severity}] clause {f.clause_ref or '-'}: {f.claim}")
    print()
    return len(findings)


async def _main() -> int:
    load_dotenv()

    ran: list[str] = []

    # 1) native worker on OpenAI
    if os.environ.get("OPENAI_API_KEY", "").strip():
        from agent_exchange.core import make_backend
        from agent_exchange.workers.specialist import SpecialistWorker

        model = os.environ.get("OPENAI_MODEL", "gpt-4.1-mini")
        n = await _run(
            "native", "openai", model,
            lambda: SpecialistWorker(_NAME, _AREA, _PROMPT, backend=make_backend("openai", model)),
        )
        if n:
            ran.append("native/OpenAI")
    else:
        print("  (native/OpenAI skipped — OPENAI_API_KEY unset)\n")

    # 2) LangGraph on AI/ML API
    if os.environ.get("AIMLAPI_API_KEY", "").strip():
        from agent_exchange.workers.langgraph_specialist import LangGraphSpecialist

        model = os.environ.get("AIMLAPI_MODEL", "<default>")
        n = await _run(
            "LangGraph", "AI/ML API", model,
            lambda: LangGraphSpecialist(_NAME, _AREA, _PROMPT),
        )
        if n:
            ran.append("LangGraph/AI-ML-API")
    else:
        print("  (LangGraph/AI-ML-API skipped — AIMLAPI_API_KEY unset)\n")

    # 3) CrewAI on Featherless (open-weight)
    if os.environ.get("FEATHERLESS_API_KEY", "").strip() and os.environ.get("FEATHERLESS_MODEL", "").strip():
        from agent_exchange.workers.crewai_specialist import CrewAISpecialist

        model = os.environ.get("FEATHERLESS_MODEL", "")
        n = await _run(
            "CrewAI", "Featherless", model,
            lambda: CrewAISpecialist(_NAME, _AREA, _PROMPT),
        )
        if n:
            ran.append("CrewAI/Featherless")
    else:
        print("  (CrewAI/Featherless skipped — FEATHERLESS_API_KEY / FEATHERLESS_MODEL unset)\n")

    _hr()
    print(f"  {len(ran)} framework(s) audited the SAME contract: {', '.join(ran) or 'none'}")
    _hr()
    return 0 if ran else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
