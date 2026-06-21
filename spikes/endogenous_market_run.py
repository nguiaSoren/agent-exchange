"""LIVE endogenous-leak experiment — the leak rate EMERGES from a persistent liar attacking
the real judge in-loop, instead of being supplied from Paper A's F-H.

The reviewer's standing objection to E5: the strategic liar's leak (0.25) was *read off*
Paper A and *injected*, so the sim could only propagate an exploit the verifier already
exhibited, never surface a new one. This run removes that: a persistent strategic liar runs
MANY adaptive attacks against the LIVE verifier (a market round = one adaptive attempt),
and the leak is the MEASURED breach rate over the campaign — emergent, not supplied. The
novel question a single bounded run (F-H: 4 docs × 12 rounds) cannot answer: does a liar with
a large *cumulative* attack budget eventually breach a judge that held under one bounded
attack (does sustained pressure compound)?

Two judge regimes: frontier (gpt-4.1) and weak (gpt-4.1-mini); oracle gpt-5.1 (off-panel) for
ground-truth falsity; attacker panel gpt-4.1/gpt-5.1/claude. Each attempt is a bounded adaptive
attack; a breach = the target auto-pays a claim the oracle rejects. We then feed the EMERGENT
leak back into the population sim so the market dynamics use a measured, not supplied, L.

Env: OPENAI_API_KEY + AIMLAPI_API_KEY. ATTEMPTS (default 12), ATTACK_ROUNDS (default 6).
Output: data/eval/endogenous_market_report.json. Bounded + live (spends).
"""

from __future__ import annotations

import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from dotenv import load_dotenv

from agent_exchange.core import make_backend
from agent_exchange.eval.adaptive_adversary import run_adaptive_attack
from agent_exchange.eval.long_corpus import load_long_contracts
from agent_exchange.eval.market_sim import run_sim
from agent_exchange.verify import Verifier

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(_ROOT, ".env"))
_CONTRACTS = os.path.join(_ROOT, "data", "eval", "long_contracts.json")
_REPORT = os.path.join(_ROOT, "data", "eval", "endogenous_market_report.json")

REGIMES = {  # judge under attack
    "frontier_judge": ("openai", "gpt-4.1"),
    "weak_judge": ("openai", "gpt-4.1-mini"),
}


async def _campaign(judge, docs, attacker_panel, oracle, *, n_attempts, rounds):
    """A persistent liar: n_attempts bounded adaptive attacks vs `judge`, cycling docs.

    Logs the FULL per-round adaptation of each attack (strategy, claim, the verdict it
    conditioned the next round on) — the evidence that the search was genuinely adaptive,
    not 12 near-identical resamples. Reports per-attempt distinct-strategy / distinct-claim
    counts so a reviewer can see escalation, not just the leak number.
    """
    breaches = 0
    log = []
    cumulative = []
    total_rounds = 0
    distinct_strats = []
    distinct_claims = []
    for i in range(n_attempts):
        doc = docs[i % len(docs)]
        res = await run_adaptive_attack(doc, target=judge, oracle=oracle,
                                        attacker_panel=attacker_panel, max_rounds=rounds)
        breaches += int(res.breached)
        cumulative.append(round(breaches / (i + 1), 4))
        total_rounds += res.rounds_used
        ds = len({a.strategy for a in res.attempts})
        dc = len({a.claim for a in res.attempts})
        distinct_strats.append(ds)
        distinct_claims.append(dc)
        log.append({
            "attempt": i, "breached": res.breached, "rounds_used": res.rounds_used,
            "doc": res.document_preview,
            "n_distinct_strategies": ds, "n_distinct_claims": dc,
            "adaptation": [
                {"round": a.round, "strategy": a.strategy, "claim": a.claim[:140],
                 "target_verdict": a.target_verdict, "target_conf": round(a.target_confidence, 2),
                 "auto_pays": a.target_auto_pays, "oracle": a.oracle_verdict}
                for a in res.attempts
            ],
        })
        print(f"      attempt {i}: {'BREACH' if res.breached else 'held'} "
              f"({res.rounds_used} rounds, {ds} strategies, {dc} distinct claims)")
    n = max(1, n_attempts)
    return {"n_attempts": n_attempts, "breaches": breaches,
            "emergent_leak": round(breaches / n, 4),
            "cumulative_leak": cumulative, "log": log,
            "adaptation_check": {  # evidence the search was real, not resampling
                "avg_rounds_per_attempt": round(total_rounds / n, 2),
                "avg_distinct_strategies": round(sum(distinct_strats) / n, 2),
                "avg_distinct_claims": round(sum(distinct_claims) / n, 2),
            }}


async def _main() -> None:
    if not (os.getenv("OPENAI_API_KEY") or "").strip() or not (os.getenv("AIMLAPI_API_KEY") or "").strip():
        print("Need OPENAI_API_KEY + AIMLAPI_API_KEY. Exiting.")
        return
    docs = load_long_contracts(_CONTRACTS)
    n_attempts = int(os.getenv("ATTEMPTS", "12"))
    rounds = int(os.getenv("ATTACK_ROUNDS", "6"))
    oracle = Verifier(make_backend("aimlapi", "gpt-5.1-2025-11-13"))
    panel = [make_backend("openai", "gpt-4.1"), make_backend("aimlapi", "gpt-5.1-2025-11-13"),
             make_backend("aimlapi", "anthropic/claude-haiku-4.5")]

    report = {"n_attempts": n_attempts, "attack_rounds": rounds, "n_docs": len(docs),
              "oracle": "gpt-5.1", "supplied_L_from_FH": {"frontier": 0.0, "weak": 0.25}, "regimes": {}}
    for rname, (prov, model) in REGIMES.items():
        print(f"\n=== {rname} ({prov}:{model}) — {n_attempts} persistent attempts × {rounds} rounds ===")
        judge = Verifier(make_backend(prov, model))
        camp = await _campaign(judge, docs, panel, oracle, n_attempts=n_attempts, rounds=rounds)
        emergent = camp["emergent_leak"]
        # Feed the EMERGENT leak into the population sim (strategic liars use it; naive ~0).
        sim_runs = [run_sim(liar_fraction=0.5, leak_rate=0.0, adversary="strategic",
                            strategic_leak_rate=emergent, rounds=400, seed=s) for s in range(5)]
        ill = sum(r.ill_gotten_total for r in sim_runs) / len(sim_runs)
        liar = sum(r.avg_liar_earn for r in sim_runs) / len(sim_runs)
        hon = sum(r.avg_honest_earn for r in sim_runs) / len(sim_runs)
        report["regimes"][rname] = {**camp, "population_under_emergent_L": {
            "emergent_leak": emergent, "ill_gotten_mean": round(ill, 4),
            "avg_liar_earn": round(liar, 4), "avg_honest_earn": round(hon, 4)}}
        print(f"  EMERGENT leak = {emergent:.0%} ({camp['breaches']}/{n_attempts})  "
              f"(supplied from F-H: {report['supplied_L_from_FH']['frontier' if 'frontier' in rname else 'weak']:.0%})")
        print(f"  population under emergent L: ill-gotten ${ill:.3f}, avg_liar ${liar:.2f} vs avg_honest ${hon:.2f}")

    json.dump(report, open(_REPORT, "w"), indent=2)
    print(f"\nReport → {_REPORT}")
    print("\n=== HEADLINE ===")
    for rname, r in report["regimes"].items():
        print(f"  {rname}: emergent L = {r['emergent_leak']:.0%}  (cumulative: {r['cumulative_leak']})")


if __name__ == "__main__":
    try:
        asyncio.run(_main())
    except KeyboardInterrupt:
        print("\nAborted — no further calls.")
