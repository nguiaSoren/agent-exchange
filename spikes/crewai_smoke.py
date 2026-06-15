"""LIVE smoke (L3): a real CrewAISpecialist (CrewAI brain) on Featherless (open-weight).

Builds the LIABILITY specialist from the SAME `SPECIALISTS` triple the native worker
uses, runs a genuine CrewAI Agent/Task/Crew against the Featherless model in
`FEATHERLESS_MODEL`, and prints the parsed `Finding`s. Proves the cross-framework +
open-weight path settles real, checkable findings.

Run:  ./.venv/bin/python spikes/crewai_smoke.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from dotenv import load_dotenv

from agent_exchange.workers.crewai_specialist import CrewAISpecialist
from agent_exchange.workers.specialist import SPECIALISTS

# Keep CrewAI telemetry quiet for a clean smoke.
os.environ.setdefault("OTEL_SDK_DISABLED", "true")
os.environ.setdefault("CREWAI_DISABLE_TELEMETRY", "true")

_REPLAY = (
    Path(__file__).resolve().parent.parent
    / "data/replays/sample-contract-audit-seeded-liar.replay.json"
)


def _sample_contract() -> str:
    data = json.loads(_REPLAY.read_text())
    return data["events"][0]["data"]["document_text"]


async def main() -> None:
    load_dotenv()
    model = os.environ.get("FEATHERLESS_MODEL", "").strip()
    print(f"FEATHERLESS_MODEL = {model!r}")
    if not model:
        raise SystemExit("FEATHERLESS_MODEL is unset — set it in .env first.")

    name, area, prompt = SPECIALISTS[0]  # liability
    spec = CrewAISpecialist(name=name, area=area, system_prompt=prompt)  # builds real Featherless LLM
    contract = _sample_contract()
    print(f"Running CrewAI '{name}' specialist on Featherless ({len(contract)} chars of contract)...\n")

    findings = await spec.findings(contract)
    print(f"Parsed {len(findings)} finding(s):\n")
    for f in findings:
        print(f"  [{f.severity:6}] {f.clause_ref or '(no ref)':12} {f.claim}")
    if not findings:
        print("  (no findings parsed — see fail-soft path)")


if __name__ == "__main__":
    asyncio.run(main())
