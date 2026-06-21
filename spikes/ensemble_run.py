"""LIVE ensemble judging — does a panel close the weak-judge leak (F-H)?

Two measurements:
  PART 1 (cost/benefit on the labeled set): payment-lens leak + genuine served + false-escalate
    for {mini alone, gpt-4.1 alone, ENSEMBLE[mini, gpt-4.1]} on the long-doc fixture.
  PART 2 (the leak test): re-run the scaled adaptive attack with target = ENSEMBLE[mini, gpt-4.1]
    and an INDEPENDENT oracle (gpt-5.1, not on the panel). F-H breached mini-alone 1/4; the
    ensemble should hold 0/4 because a peer vetoes the weak judge's wrong confirm.

Env: OPENAI_API_KEY + AIMLAPI_API_KEY. Output: data/eval/ensemble_report.json.
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
from agent_exchange.eval.payment_lens import collect_verdicts, score_payment_lens
from agent_exchange.eval.seeded_liar import load_fixture
from agent_exchange.eval.types import GENUINE
from agent_exchange.verify import Verifier
from agent_exchange.verify.ensemble import EnsembleVerifier

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(_ROOT, ".env"))
_CONTRACTS = os.path.join(_ROOT, "data", "eval", "long_contracts.json")
_FIXTURE = os.path.join(_ROOT, "data", "eval", "long_doc_fixture.json")
_REPORT = os.path.join(_ROOT, "data", "eval", "ensemble_report.json")


def _cls(rep, src, attr):
    for c in rep.classes:
        if c.source == src:
            return getattr(c, attr)
    return 0.0


async def _main() -> None:
    if not (os.getenv("OPENAI_API_KEY") or "").strip() or not (os.getenv("AIMLAPI_API_KEY") or "").strip():
        print("Need OPENAI_API_KEY + AIMLAPI_API_KEY — exiting.")
        return
    cases = load_fixture(_FIXTURE)
    docs = load_long_contracts(_CONTRACTS)

    mini = Verifier(make_backend("openai", "gpt-4.1-mini"))
    strong = Verifier(make_backend("openai", "gpt-4.1"))
    ensemble = EnsembleVerifier([Verifier(make_backend("openai", "gpt-4.1-mini")),
                                 Verifier(make_backend("openai", "gpt-4.1"))])

    report = {"part1_payment_lens": {}, "part2_adaptive": {}}

    # ---- PART 1: cost/benefit on the labeled fixture ----
    print("=== PART 1: payment-lens (leak / served / false-escalate) ===")
    for name, v in [("mini_alone", mini), ("gpt41_alone", strong), ("ensemble_mini+gpt41", ensemble)]:
        pairs = await collect_verdicts(cases, v)
        rep = score_payment_lens(pairs, config=name)
        gifted_leak = _cls(rep, "llm_gifted_span", "leak_rate")
        served = _cls(rep, GENUINE, "served_rate")
        fesc = _cls(rep, GENUINE, "false_escalate_rate")
        report["part1_payment_lens"][name] = {"gifted_leak_rate": gifted_leak, "genuine_served_rate": served,
                                              "genuine_false_escalate_rate": fesc}
        print(f"  {name:22s} gifted_leak={gifted_leak:.0%}  genuine_served={served:.0%}  false_escalate={fesc:.0%}")

    # ---- PART 2: adaptive attack vs the ensemble (oracle independent of the panel) ----
    print("\n=== PART 2: scaled adaptive attack vs ENSEMBLE (oracle gpt-5.1, off-panel) ===")
    oracle = Verifier(make_backend("aimlapi", "gpt-5.1-2025-11-13"))
    panel = [make_backend("openai", "gpt-4.1"), make_backend("aimlapi", "gpt-5.1-2025-11-13"),
             make_backend("aimlapi", "anthropic/claude-haiku-4.5")]
    target = EnsembleVerifier([Verifier(make_backend("openai", "gpt-4.1-mini")),
                               Verifier(make_backend("openai", "gpt-4.1"))])
    sem = asyncio.Semaphore(3)

    async def _one(doc):
        async with sem:
            return await run_adaptive_attack(doc, target=target, oracle=oracle, attacker_panel=panel, max_rounds=12)

    results = await asyncio.gather(*[_one(d) for d in docs])
    n_breached = sum(r.breached for r in results)
    print(f"  ENSEMBLE breached {n_breached}/{len(results)} docs  (mini-alone baseline from F-H: 1/4)")
    for r in results:
        if r.breached:
            for a in r.attempts:
                if a.breached:
                    print(f"    BREACH: {a.claim}")
    report["part2_adaptive"] = {"target": "ensemble[gpt-4.1-mini, gpt-4.1]", "oracle": "gpt-5.1",
                                "n_docs": len(results), "n_breached": n_breached,
                                "mini_alone_baseline": 1}

    json.dump(report, open(_REPORT, "w"), indent=2)
    print(f"\nReport → {_REPORT}")
    print("\n=== HEADLINE ===")
    p1 = report["part1_payment_lens"]
    print(f"  leak: mini {p1['mini_alone']['gifted_leak_rate']:.0%} / ensemble {p1['ensemble_mini+gpt41']['gifted_leak_rate']:.0%}")
    print(f"  genuine served: mini {p1['mini_alone']['genuine_served_rate']:.0%} / ensemble {p1['ensemble_mini+gpt41']['genuine_served_rate']:.0%} (ensemble cost = more escalation)")
    print(f"  adaptive breaches: mini-alone 1/4 → ensemble {n_breached}/{len(results)}")


if __name__ == "__main__":
    try:
        asyncio.run(_main())
    except KeyboardInterrupt:
        print("\nAborted — no further calls.")
