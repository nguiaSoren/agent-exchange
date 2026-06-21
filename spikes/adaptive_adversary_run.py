"""LIVE adaptive adversary — does a PAIR-style red-team loop open a leak the static one couldn't?

The static gifted-span attack got 0% leak against every judge (F-A/F-C). This run lets an
ADAPTIVE attacker (modeled on ROGUE's PAIR refine loop, `eval/adaptive_adversary.py`) observe
each verdict and escalate toward claims the verifier mis-rules. A BREACH = the TARGET verifier
auto-pays a claim that an independent STRONGER ORACLE marks false.

Two configs over the frozen long contracts:
  1. capability-gap : target gpt-4.1-mini, oracle gpt-4.1     (can a weaker judge be beaten?)
  2. frontier       : target gpt-4.1,      oracle gpt-5.1     (can the BEST judge be beaten?)
Attacker = gpt-4.1 throughout. Compare breach rate to the static baseline (0).

Env: OPENAI_API_KEY (+ AIMLAPI_API_KEY for the gpt-5.1 oracle). ADAPTIVE_ROUNDS (default 5),
     ADAPTIVE_CONFIGS (comma list of {capability_gap,frontier}; default both).
Output: data/eval/adaptive_adversary_report.json (per-config breach stats + every attempt, auditable).
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from dataclasses import asdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from dotenv import load_dotenv

from agent_exchange.core import make_backend
from agent_exchange.eval.adaptive_adversary import run_adaptive_attack
from agent_exchange.eval.long_corpus import load_long_contracts
from agent_exchange.verify import Verifier

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(_ROOT, ".env"))
_CONTRACTS = os.path.join(_ROOT, "data", "eval", "long_contracts.json")
_REPORT = os.path.join(_ROOT, "data", "eval", "adaptive_adversary_report.json")

# config name → (target (prov,model), oracle (prov,model), attacker (prov,model))
_CONFIGS = {
    "capability_gap": (("openai", "gpt-4.1-mini"), ("openai", "gpt-4.1"), ("openai", "gpt-4.1")),
    "frontier": (("openai", "gpt-4.1"), ("aimlapi", "gpt-5.1-2025-11-13"), ("openai", "gpt-4.1")),
}


async def _run_config(name, docs, rounds) -> dict:
    (tp, tm), (op, om), (ap, am) = _CONFIGS[name]
    # Cross-provider key guard (honest skip if a needed key is missing).
    need = {tp, op, ap}
    keymap = {"openai": "OPENAI_API_KEY", "aimlapi": "AIMLAPI_API_KEY", "featherless": "FEATHERLESS_API_KEY"}
    missing = [p for p in need if not (os.getenv(keymap.get(p, "")) or "").strip()]
    if missing:
        print(f"[skip {name}] missing keys for providers {missing}")
        return {"skipped": True, "missing": missing}

    print(f"\n{'='*64}\n# CONFIG {name}: target={tp}:{tm}  oracle={op}:{om}  attacker={ap}:{am}  rounds={rounds}\n{'='*64}")
    target = Verifier(make_backend(tp, tm))
    oracle = Verifier(make_backend(op, om))
    attacker = make_backend(ap, am)
    sem = asyncio.Semaphore(4)

    async def _one(doc):
        async with sem:
            return await run_adaptive_attack(doc, target=target, oracle=oracle, attacker=attacker, max_rounds=rounds)

    results = await asyncio.gather(*[_one(d) for d in docs])
    n_breached = sum(r.breached for r in results)
    total_attempts = sum(r.rounds_used for r in results)
    first_breach_rounds = [next((a.round for a in r.attempts if a.breached), None) for r in results]
    print(f"  BREACHED {n_breached}/{len(results)} docs  (static baseline: 0)  · total attempts {total_attempts}")
    for r in results:
        tag = "BREACH" if r.breached else "held"
        print(f"    [{tag}] {r.document_preview!r} — {r.rounds_used} rounds")
        for a in r.attempts:
            mark = " <== BREACH" if a.breached else ""
            print(f"        r{a.round} [{a.strategy}] target={a.target_verdict}({a.target_confidence:.2f}) oracle={a.oracle_verdict}{mark}")
            if a.breached:
                print(f"            CLAIM: {a.claim}")
    return {
        "skipped": False, "target": f"{tp}:{tm}", "oracle": f"{op}:{om}", "attacker": f"{ap}:{am}",
        "rounds": rounds, "n_docs": len(results), "n_breached": n_breached,
        "breach_rate": n_breached / len(results) if results else 0.0,
        "total_attempts": total_attempts,
        "first_breach_rounds": first_breach_rounds,
        "results": [{"document_preview": r.document_preview, "breached": r.breached,
                     "rounds_used": r.rounds_used, "attempts": [asdict(a) for a in r.attempts]}
                    for r in results],
    }


async def _main() -> None:
    if not (os.getenv("OPENAI_API_KEY") or "").strip():
        print("OPENAI_API_KEY not set — exiting, no spend.")
        return
    if not os.path.exists(_CONTRACTS):
        print(f"Missing {_CONTRACTS} — run spikes/long_doc_gate_run.py first.")
        return
    docs = load_long_contracts(_CONTRACTS)
    rounds = int(os.getenv("ADAPTIVE_ROUNDS", "5"))
    want = [c.strip() for c in os.getenv("ADAPTIVE_CONFIGS", "capability_gap,frontier").split(",") if c.strip()]
    print(f"Loaded {len(docs)} long contracts. Configs: {want}. This spends real money on attacker+target+oracle calls.")

    report = {"n_docs": len(docs), "rounds": rounds, "configs": {}}
    for name in want:
        if name not in _CONFIGS:
            print(f"[skip] unknown config {name!r}")
            continue
        report["configs"][name] = await _run_config(name, docs, rounds)

    with open(_REPORT, "w") as f:
        json.dump(report, f, indent=2)
    print(f"\nReport → {_REPORT}")
    print("\n=== HEADLINE ===")
    for name, c in report["configs"].items():
        if c.get("skipped"):
            print(f"  {name}: skipped ({c.get('missing')})")
        else:
            print(f"  {name}: breached {c['n_breached']}/{c['n_docs']} docs (static baseline 0) — target {c['target']} vs oracle {c['oracle']}")


if __name__ == "__main__":
    try:
        asyncio.run(_main())
    except KeyboardInterrupt:
        print("\nAborted — no further calls.")
