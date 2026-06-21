"""E5 — population-mix robustness sweep (offline; the experiment that lifts Paper B).

Sweeps liar-fraction × verifier-leak-rate × {naive, strategic} liar, multiple seeds, over the
REAL reputation + Thompson-hiring code (`eval/market_sim.py`). Answers: does the market stay
self-cleaning (paid-fabrication earnings → 0; honest workers carry the value and the hires)
even when liars dominate the population — and how does that depend on the verifier's leak
rate (Paper A's frontier ~0 vs weak ~0.25)?

Deterministic, no LLM/network. Output: data/eval/population_mix_report.json. Run:
    .venv/bin/python spikes/population_mix_run.py
"""

from __future__ import annotations

import json
import os
import statistics
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from agent_exchange.eval.market_sim import run_sim

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_REPORT = os.path.join(_ROOT, "data", "eval", "population_mix_report.json")

LIAR_FRACTIONS = [0.1, 0.3, 0.5, 0.7, 0.9]
LEAK_RATES = [0.0, 0.1, 0.25]   # 0.0 = frontier judge (Paper A); 0.25 = weak gpt-4.1-mini (F-H 1/4)
ADVERSARIES = ["naive", "strategic"]
SEEDS = list(range(8))
ROUNDS = 400
N_WORKERS = 20


def _agg(results, attr):
    xs = [getattr(r, attr) for r in results]
    return {"mean": round(statistics.mean(xs), 6),
            "stdev": round(statistics.pstdev(xs), 6) if len(xs) > 1 else 0.0}


def main() -> None:
    cells = []
    for adv in ADVERSARIES:
        for L in LEAK_RATES:
            for f in LIAR_FRACTIONS:
                runs = [run_sim(n_workers=N_WORKERS, liar_fraction=f, leak_rate=L,
                                adversary=adv, rounds=ROUNDS, seed=s) for s in SEEDS]
                cell = {
                    "adversary": adv, "leak_rate": L, "liar_fraction": f,
                    "ill_gotten_total": _agg(runs, "ill_gotten_total"),
                    "liar_total_earn": _agg(runs, "liar_total_earn"),
                    "liar_fab_earn": _agg(runs, "liar_fab_earn"),
                    "honest_total_earn": _agg(runs, "honest_total_earn"),
                    "honest_hire_share": _agg(runs, "honest_hire_share"),
                    "avg_honest_earn": _agg(runs, "avg_honest_earn"),
                    "avg_liar_earn": _agg(runs, "avg_liar_earn"),
                    "final_avg_honest_rep": _agg(runs, "final_avg_honest_rep"),
                    "final_avg_liar_rep": _agg(runs, "final_avg_liar_rep"),
                }
                cells.append(cell)
                print(f"[{adv:9s} L={L:.2f} f={f:.1f}]  ill-gotten={cell['ill_gotten_total']['mean']:.3f}  "
                      f"honest_hire_share={cell['honest_hire_share']['mean']:.0%}  "
                      f"avg_honest=${cell['avg_honest_earn']['mean']:.2f} avg_liar=${cell['avg_liar_earn']['mean']:.2f}")

    # Grounded judge regimes: leak rate per ADVERSARY STRATEGY, from Paper A's measured runs.
    # Frontier judge: even an adaptive/strategic attack gets 0/4 (F-F/F-H) → L=0 for both.
    # Weak judge (gpt-4.1-mini): a static/naive gifted-span lie is caught (~0, F-A), but an
    # adaptive/strategic attack breaches 1/4 (F-H) → L_strategic=0.25, L_naive=0.
    regimes = {
        "frontier_judge": {"naive_leak": 0.0, "strategic_leak": 0.0},
        "weak_judge": {"naive_leak": 0.0, "strategic_leak": 0.25},
    }
    grounded = {}
    print("\n=== GROUNDED JUDGE REGIMES (strategy-dependent leak, from Paper A) ===")
    for rname, cfg in regimes.items():
        grounded[rname] = {}
        for adv in ADVERSARIES:
            base_L = cfg["naive_leak"]  # naive class leak
            strat_L = cfg["strategic_leak"] if adv == "strategic" else None
            runs = [run_sim(n_workers=N_WORKERS, liar_fraction=0.5, leak_rate=base_L,
                            adversary=adv, strategic_leak_rate=strat_L, rounds=ROUNDS, seed=s)
                    for s in SEEDS]
            grounded[rname][adv] = {
                "ill_gotten_total": _agg(runs, "ill_gotten_total"),
                "liar_total_earn": _agg(runs, "liar_total_earn"),
                "avg_liar_earn": _agg(runs, "avg_liar_earn"),
                "avg_honest_earn": _agg(runs, "avg_honest_earn"),
                "honest_hire_share": _agg(runs, "honest_hire_share"),
            }
            g = grounded[rname][adv]
            print(f"  [{rname:14s} {adv:9s} f=0.5]  ill-gotten=${g['ill_gotten_total']['mean']:.3f}  "
                  f"avg_liar=${g['avg_liar_earn']['mean']:.2f} avg_honest=${g['avg_honest_earn']['mean']:.2f}  "
                  f"honest_hire={g['honest_hire_share']['mean']:.0%}")

    report = {"n_workers": N_WORKERS, "rounds": ROUNDS, "seeds": len(SEEDS), "bid_usdc": 0.05,
              "liar_fractions": LIAR_FRACTIONS, "leak_rates": LEAK_RATES, "adversaries": ADVERSARIES,
              "note": "leak_rate models the verifier: 0.0=frontier judge (Paper A), 0.25=weak gpt-4.1-mini (F-H 1/4)",
              "cells": cells, "grounded_regimes": grounded}
    os.makedirs(os.path.dirname(_REPORT), exist_ok=True)
    json.dump(report, open(_REPORT, "w"), indent=2)
    print(f"\nReport → {_REPORT}")

    # Headline extraction.
    def cell(adv, L, f):
        return next(c for c in cells if c["adversary"] == adv and c["leak_rate"] == L and c["liar_fraction"] == f)
    print("\n=== HEADLINE ===")
    for adv in ADVERSARIES:
        ig_L0 = max(cell(adv, 0.0, f)["ill_gotten_total"]["mean"] for f in LIAR_FRACTIONS)
        ig_L25 = cell(adv, 0.25, 0.5)["ill_gotten_total"]["mean"]
        hs_L0_f90 = cell(adv, 0.0, 0.9)["honest_hire_share"]["mean"]
        print(f"  {adv}: max ill-gotten @ L=0 (any liar fraction) = ${ig_L0:.3f}  |  "
              f"@ L=0.25,f=0.5 = ${ig_L25:.3f}  |  honest hire-share @ L=0,f=0.9 = {hs_L0_f90:.0%}")


if __name__ == "__main__":
    main()
