"""Targeted numeric-aggregation attack battery -- the cheap, oracle-free way to turn the
existence-proof (gpt-5 auto-paid 2 fabricated aggregations in the locate audit) into a
HAND-ADJUDICATED rate.

The two-tailed audit found the discriminating attack class is numeric/temporal AGGREGATION: a
claim asserting a derived total/period the contract never states as a term (e.g. "8-year
confidentiality = 3-year term + 5-year survival"). The general attacker only stumbles into it
occasionally, and gpt-5.1 never faced it, so its immunity is untested. This battery fires ONLY
the aggregation strategy at each target, many times, and logs every AUTO-PAY (target confirms,
conf >= threshold, not escalated) with the claim -- for the operator to HAND-ADJUDICATE against
the contracts. No oracle pool: the human is the oracle (more rigorous than the cheap automated
oracles that just under-counted). Cost = attacker (cheap) + target calls only; run at LOW R.

Per attack: up to ROUNDS aggregation claims (each conditioned on the target's prior verdict),
stopping at the first auto-pay. Rate = (attacks with an auto-pay) / N. The auto-paid claims are
dumped for hand audit; k of them that assert non-existent terms is the human-confirmed leak.

Env: OPENROUTER_API_KEY. JUDGES="label=provider:model,..." (default mid/gpt5/gpt5.1);
     ATTACKER="provider:model" (default cheap gpt-4.1-mini); N (attacks/target, default 20);
     ROUNDS (default 3, LOW R); CONCURRENCY (default 8); MAX_ATTACKS (spend cap).
Output: data/eval/aggregation_battery_report.json  (checkpointed; auto-paid claims per target).

  cd agent-exchange && N=20 ROUNDS=3 MAX_ATTACKS=80 .venv/bin/python spikes/aggregation_battery.py
  DRY_RUN=1 .venv/bin/python spikes/aggregation_battery.py        # plan only, no spend
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from dotenv import load_dotenv

from agent_exchange.core import make_backend
from agent_exchange.core.backend import PROVIDERS
from agent_exchange.eval.adaptive_adversary import (
    STRATEGY_LADDER, _attacker_claim, _build_refine_user, _build_seed_user, _verdict_for)
from agent_exchange.eval.long_corpus import load_long_contracts
from agent_exchange.verify import Verifier
from agent_exchange.verify.schema import DEFAULT_THRESHOLD, Verdict

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(_ROOT, ".env"))
_CONTRACTS = os.path.join(_ROOT, "data", "eval", "long_contracts.json")
_REPORT = os.path.join(_ROOT, "data", "eval", "aggregation_battery_report.json")

AGG = next((n, d) for (n, d) in STRATEGY_LADDER if n == "numeric_aggregation")
DEFAULT_JUDGES = ("mid=openrouter:openai/gpt-4.1,"
                  "gpt5=openrouter:openai/gpt-5,"
                  "frontier=openrouter:openai/gpt-5.1")


def _pm(s):
    p, m = s.split(":", 1)
    return (p.strip(), m.strip())


def _save(report):
    json.dump(report, open(_REPORT, "w"), indent=2)


async def _one_attack(sem, target, attacker, doc, rounds, threshold):
    """One aggregation attack: up to `rounds` aggregation claims, stop at the first target
    auto-pay. Returns the auto-paid claim record (or None)."""
    async with sem:
        name, desc = AGG
        prev = None
        for r in range(rounds):
            user = (_build_seed_user(doc, name, desc) if prev is None else
                    _build_refine_user(doc, prev[0], prev[1], prev[2], name, desc))
            try:
                claim = await _attacker_claim(attacker, user)
                if not claim:
                    continue
                tv = await _verdict_for(target, doc, claim)
            except Exception:  # noqa: BLE001 - a dead round is skipped, never crashes the battery
                continue
            if tv is None:
                continue
            auto = (tv.verdict is Verdict.CONFIRMED and tv.confidence >= threshold
                    and not tv.needs_human(threshold))
            if auto:
                return {"round": r, "claim": claim, "confidence": round(tv.confidence, 2),
                        "doc_preview": doc.strip()[:60]}
            prev = (claim, tv.verdict.value, tv.reason)
        return None


async def _main():
    sys.stdout.reconfigure(line_buffering=True)
    if not (os.getenv("OPENROUTER_API_KEY") or "").strip():
        print("Need OPENROUTER_API_KEY. Exiting."); return
    judges = [(lbl, *_pm(pm)) for lbl, pm in (x.split("=", 1) for x in
              os.getenv("JUDGES", DEFAULT_JUDGES).split(",") if x.strip())]
    n = int(os.getenv("N", "20"))
    rounds = int(os.getenv("ROUNDS", "3"))
    max_attacks = int(os.getenv("MAX_ATTACKS", "100000"))
    attacker_pm = _pm(os.getenv("ATTACKER", "openrouter:openai/gpt-4.1-mini"))

    print("=== aggregation battery plan ===")
    for (lbl, _, model) in judges:
        print(f"  {lbl:>10} ({model}): {n} attacks x <= {rounds} rounds  (<= {n * rounds * 2} LLM calls)")
    print(f"  attacker {attacker_pm[1]} (cheap); NO oracle pool (human-adjudicated); cap {max_attacks} attacks")
    if (os.getenv("DRY_RUN") or "").strip() == "1":
        print("DRY_RUN=1 -> plan only, no spend."); return

    docs = load_long_contracts(_CONTRACTS)
    attacker = make_backend(*attacker_pm)
    sem = asyncio.Semaphore(int(os.getenv("CONCURRENCY", "8")))
    start = time.monotonic()
    report = {"design": {"judges": [j[0] for j in judges], "n_per_target": n, "rounds": rounds,
                         "attacker": attacker_pm[1], "oracle": "HUMAN (hand-adjudicated)"},
              "note": "auto_pays = target CONFIRMED an aggregation claim. HAND-ADJUDICATE each: "
                      "k that assert a non-existent contract term is the human-confirmed leak.",
              "targets": {}}
    attacks_done = 0
    for (lbl, prov, model) in judges:
        if attacks_done >= max_attacks:
            break
        target = Verifier(make_backend(prov, model))
        print(f"\n=== target '{lbl}' ({prov}:{model}) ===")
        budget = min(n, max_attacks - attacks_done)
        tasks = [_one_attack(sem, target, attacker, docs[i % len(docs)], rounds, DEFAULT_THRESHOLD)
                 for i in range(budget)]
        results = await asyncio.gather(*tasks)
        attacks_done += budget
        autopays = [r for r in results if r]
        report["targets"][lbl] = {
            "model": f"{prov}:{model}", "n_attacks": budget,
            "auto_pays": len(autopays), "auto_pay_rate": round(len(autopays) / max(1, budget), 3),
            "auto_paid_claims": autopays}  # <- hand-adjudicate these
        _save(report)
        print(f"  auto-pays: {len(autopays)}/{budget} (rate {len(autopays) / max(1, budget):.2f}) "
              f"-> hand-adjudicate the {len(autopays)} claims")

    _save(report)
    print(f"\nReport -> {_REPORT}  ({(time.monotonic() - start) / 60:.1f} min)")
    print("=== AUTO-PAY RATES (pre-adjudication; the human step decides how many are fabrications) ===")
    for lbl, t in report["targets"].items():
        print(f"  {lbl:>10} {t['model'].split('/')[-1]:14s}: {t['auto_pays']}/{t['n_attacks']} auto-paid")


if __name__ == "__main__":
    try:
        asyncio.run(_main())
    except KeyboardInterrupt:
        print("\nAborted - no further calls.")
