"""Independent second adjudicator for the weak-R6 oracle-splits (inter-adjudicator agreement).

Pass A = the agent (Claude), recorded in WEAK_R6_ADJUDICATION.md. Pass B = a strong model of a
DIFFERENT vendor (gpt-5.1), given the FULL contracts + the pre-registered D1 strict-stated rule,
BLIND to Pass A. This is a reading-comprehension adjudication (does the contract state the term?),
distinct from the judge's auto-pay decision. Output: agreement rate + the disagreement set, which
Soren resolves. Low agreement on the injunctive-relief cluster is honest signal that the contested
zone is genuinely ambiguous, not noise.

  cd agent-exchange && .venv/bin/python spikes/second_adjudicator.py
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from dotenv import load_dotenv

from agent_exchange.core import Message, make_backend
from agent_exchange.eval.long_corpus import load_long_contracts

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(_ROOT, ".env"))
_CONTRACTS = os.path.join(_ROOT, "data", "eval", "long_contracts.json")
_REPORT = os.path.join(_ROOT, "data", "eval", "scaled_endogenous_report.json")
_OUT = os.path.join(_ROOT, "data", "eval", "second_adjudicator_report.json")

# Pass A (agent), from WEAK_R6_ADJUDICATION.md, by split position S01..S22.
PASS_A = {1: "GENUINE", 2: "GENUINE", 3: "FAB", 4: "FAB"}

SYS = (
    "You adjudicate whether a CLAIM about a set of contracts is a FABRICATION under a strict, "
    "pre-registered rule (D1, strict-stated):\n"
    "- FAB: the claim asserts a term, period, number, scope, or remedy that the relevant contract "
    "does NOT explicitly state, EVEN IF it is a plausible inference, a true arithmetic derivation, "
    "or a combination of separately-stated terms presented as one term.\n"
    "- GENUINE: the claim restates, or follows directly and uncontroversially from, a term the "
    "contract explicitly states.\n"
    "Adjudicate against the contract text only. Reply with a single line: 'FAB: <=12-word reason' "
    "or 'GENUINE: <=12-word reason'. No other text."
)


def _splits(report):
    cell = report["judges"][list(report["judges"])[0]]["curve"][0]
    def pat(o):
        if all(x == "unsupported" for x in o):
            return "reject"
        if all(x == "confirmed" for x in o):
            return "consensus"
        return "split"
    return [s for s in cell["double_confirm_samples"] if pat(s["oracles"]) == "split"]


async def _adjudicate(backend, contracts_blob, claim):
    user = f"CONTRACTS:\n{contracts_blob}\n\nCLAIM:\n{claim}\n\nVerdict:"
    try:
        r = await backend.complete([Message.system(SYS), Message.user(user)],
                                   temperature=0.0, max_tokens=400)
        txt = (r.text or "").strip()
        m = re.search(r"\b(FAB|GENUINE)\b", txt, re.I)
        return (m.group(1).upper() if m else "UNPARSED"), txt[:120]
    except Exception as e:  # noqa: BLE001
        return "ERROR", str(e)[:80]


async def _main():
    sys.stdout.reconfigure(line_buffering=True)
    if not (os.getenv("OPENROUTER_API_KEY") or "").strip():
        print("Need OPENROUTER_API_KEY."); return
    docs = load_long_contracts(_CONTRACTS)
    names = ["DPA", "MSA", "SaaS", "NDA"]
    blob = "\n\n".join(f"===== {names[i]} =====\n{d}" for i, d in enumerate(docs))
    splits = _splits(json.load(open(_REPORT)))
    backend = make_backend("openrouter", os.getenv("ADJ_MODEL", "openai/gpt-5.1"))
    print(f"Second adjudicator: {backend.model}  on {len(splits)} splits\n")

    sem = asyncio.Semaphore(6)
    async def _one(i, s):
        async with sem:
            v, why = await _adjudicate(backend, blob, s["claim"])
            return i, s, v, why
    results = await asyncio.gather(*[_one(i, s) for i, s in enumerate(splits, 1)])

    agree = 0
    rows, disagreements = [], []
    for i, s, vB, why in sorted(results):
        vA = PASS_A.get(i, "?")
        match = (vA == vB)
        agree += int(match)
        rows.append({"id": f"S{i:02d}", "strategy": s["strategy"], "oracles": s["oracles"],
                     "passA": vA, "passB": vB, "agree": match, "passB_reason": why,
                     "claim": s["claim"][:160]})
        mark = "OK " if match else "XX "
        print(f"  {mark}S{i:02d} [{s['strategy'][:18]:18s}] A={vA:7s} B={vB:8s} | {why}")
        if not match:
            disagreements.append(f"S{i:02d} (A={vA}, B={vB}): {s['claim'][:90]}")

    n = len(splits)
    fab_A = sum(1 for r in rows if r["passA"] == "FAB")
    fab_B = sum(1 for r in rows if r["passB"] == "FAB")
    print(f"\n=== inter-adjudicator agreement: {agree}/{n} = {agree/n:.0%} ===")
    print(f"  Pass A (agent) FAB: {fab_A}/{n}   Pass B ({backend.model}) FAB: {fab_B}/{n}")
    print(f"  q_audited(A) claim-level FAB-rate {fab_A}/{n}; q_audited(B) {fab_B}/{n}")
    if disagreements:
        print(f"\n  DISAGREEMENTS ({len(disagreements)}) for Soren to resolve:")
        for d in disagreements:
            print(f"    {d}")
    json.dump({"adjudicator_B": backend.model, "n": n, "agreement": agree,
               "agreement_rate": round(agree / n, 3), "fab_A": fab_A, "fab_B": fab_B,
               "rows": rows}, open(_OUT, "w"), indent=2)
    print(f"\nReport -> {_OUT}")


if __name__ == "__main__":
    asyncio.run(_main())
