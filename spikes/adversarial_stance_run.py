"""LIVE adversarial stance run — 3-way vs 5-way on engineered HARD cross-source cases.

Generates (or loads cached) the adversarial suite (4 failure types × ~10 cases), then runs BOTH
verifiers over it across ≥3 seeds and reports, per failure type:

  * LEVEL accuracy — does the predicted Corroboration level match the case's intended level?
  * per-source STANCE accuracy — does the predicted per-source stance match the intended stance?

for `StanceCrossSourceVerifier` (3-way: support/contradict/silent) and
`RefinedStanceCrossSourceVerifier` (5-way: + partially_supports/implied, confidence-weighted).

The key question: does the 5-way taxonomy + confidence-weighting beat the 3-way on the hard
cases, and on WHICH failure types? Output: data/eval/adversarial_stance_report.json.

Seeds re-query the judges (temperature stays 0.0, but the model is non-deterministic across calls)
to estimate spread. The fixture itself is FROZEN (generated once with gpt-4.1) so both verifiers
and all seeds see the SAME cases.

Env: GEN_MODEL (gpt-4.1), CROSS_JUDGE (gpt-4.1-mini), ADV_PER_TYPE (10), ADV_SEEDS (3).
"""

from __future__ import annotations

import asyncio
import json
import os
import statistics
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from dotenv import load_dotenv

from agent_exchange.core import make_backend
from agent_exchange.eval.adversarial_stance import (
    FAILURE_TYPES,
    generate_suite,
    load_fixture,
    to_jsonable,
)
from agent_exchange.verify.cross_source_verifier import (
    RefinedStanceCrossSourceVerifier,
    StanceCrossSourceVerifier,
)

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(_ROOT, ".env"))
_FIXTURE = os.path.join(_ROOT, "data", "eval", "adversarial_stance_fixture.json")
_REPORT = os.path.join(_ROOT, "data", "eval", "adversarial_stance_report.json")

# The 3-way verifier emits only {support, contradict, silent}. To score its per-source stance
# against the 5-way intended labels FAIRLY, we collapse the intended 5-way label to the 3-way
# vocabulary the 3-way verifier *could* produce. 'implied' and 'partially_supports' have no 3-way
# home — the closest correct 3-way answer is 'support' (the source is on the claim's side, not
# contradicting/silent), so we credit the 3-way verifier when it says 'support' there. This is the
# GENEROUS reading for the 3-way classifier — it cannot lose points for lacking the finer labels.
_COLLAPSE_5_TO_3 = {
    "support": "support",
    "implied": "support",
    "partially_supports": "support",
    "contradict": "contradict",
    "silent": "silent",
}


async def _ensure_fixture() -> list:
    if os.path.exists(_FIXTURE):
        cases = load_fixture(_FIXTURE)
        print(f"Loaded frozen fixture: {len(cases)} cases from {_FIXTURE}")
        return cases
    gen_model = os.getenv("GEN_MODEL", "gpt-4.1")
    per_type = int(os.getenv("ADV_PER_TYPE", "10"))
    print(f"Generating adversarial suite with {gen_model} ({per_type}/type)...")
    gb = make_backend("openai", gen_model)
    cases = await generate_suite(gb, per_type=per_type)
    json.dump(to_jsonable(cases), open(_FIXTURE, "w"), indent=2)
    print(f"Froze {len(cases)} cases → {_FIXTURE}")
    return cases


async def _eval_verifier(verifier, cases, *, five_way: bool) -> dict:
    """Run one verifier over all cases; return per-type level-hits and per-source stance-hits."""
    by_type = {t: {"level_ok": 0, "level_n": 0, "stance_ok": 0, "stance_n": 0} for t in FAILURE_TYPES}
    rows = []
    results = await asyncio.gather(
        *[verifier.verify_claims([c.claim], c.source_pairs()) for c in cases]
    )
    for c, res in zip(cases, results):
        r = res[0]
        bt = by_type[c.type]
        level_ok = r.level.value == c.intended_level
        bt["level_n"] += 1
        bt["level_ok"] += level_ok
        pred_stances = [s.verdict for s in r.per_source]
        intended = c.intended_stances()
        case_stance_ok = 0
        for pred, want in zip(pred_stances, intended):
            target = want if five_way else _COLLAPSE_5_TO_3[want]
            hit = pred == target
            bt["stance_n"] += 1
            bt["stance_ok"] += hit
            case_stance_ok += hit
        rows.append({"type": c.type, "intended_level": c.intended_level,
                     "pred_level": r.level.value, "level_ok": level_ok,
                     "intended_stances": intended, "pred_stances": pred_stances,
                     "stance_hits": case_stance_ok, "claim": c.claim[:80]})
    return {"by_type": by_type, "rows": rows}


def _accuracy(d: dict, key_ok: str, key_n: str) -> float:
    n = d[key_n]
    return d[key_ok] / n if n else 0.0


async def _main() -> None:
    if not (os.getenv("OPENAI_API_KEY") or "").strip():
        print("OPENAI_API_KEY not set — exiting.")
        return
    judge_model = os.getenv("CROSS_JUDGE", "gpt-4.1-mini")
    n_seeds = int(os.getenv("ADV_SEEDS", "3"))
    cases = await _ensure_fixture()
    if not cases:
        print("No cases — aborting.")
        return

    three = StanceCrossSourceVerifier(make_backend("openai", judge_model))
    five = RefinedStanceCrossSourceVerifier(make_backend("openai", judge_model))

    # Per seed, per verifier: per-type level accuracy + per-type stance accuracy.
    acc = {"three_way": {t: {"level": [], "stance": []} for t in FAILURE_TYPES},
           "five_way": {t: {"level": [], "stance": []} for t in FAILURE_TYPES}}
    last_rows = {"three_way": None, "five_way": None}

    for seed in range(n_seeds):
        print(f"\n=== SEED {seed+1}/{n_seeds} (judge={judge_model}) ===")
        for name, verifier, five_way in (("three_way", three, False), ("five_way", five, True)):
            out = await _eval_verifier(verifier, cases, five_way=five_way)
            last_rows[name] = out["rows"]
            for t in FAILURE_TYPES:
                bt = out["by_type"][t]
                acc[name][t]["level"].append(_accuracy(bt, "level_ok", "level_n"))
                acc[name][t]["stance"].append(_accuracy(bt, "stance_ok", "stance_n"))
            line = "  ".join(f"{t.split('_')[0]}={_accuracy(out['by_type'][t], 'level_ok', 'level_n'):.0%}" for t in FAILURE_TYPES)
            print(f"  {name:10s} LEVEL: {line}")

    def _ms(xs):
        return {"mean": statistics.mean(xs) if xs else 0.0,
                "min": min(xs) if xs else 0.0, "max": max(xs) if xs else 0.0,
                "stdev": statistics.pstdev(xs) if len(xs) > 1 else 0.0}

    summary = {}
    for name in ("three_way", "five_way"):
        summary[name] = {}
        for t in FAILURE_TYPES:
            summary[name][t] = {"level": _ms(acc[name][t]["level"]),
                                "stance": _ms(acc[name][t]["stance"])}
        all_level = [v for t in FAILURE_TYPES for v in acc[name][t]["level"]]
        all_stance = [v for t in FAILURE_TYPES for v in acc[name][t]["stance"]]
        summary[name]["overall"] = {"level": _ms(all_level), "stance": _ms(all_stance)}

    n_by_type = {t: sum(1 for c in cases if c.type == t) for t in FAILURE_TYPES}
    report = {"judge": judge_model, "gen_model": os.getenv("GEN_MODEL", "gpt-4.1"),
              "n_seeds": n_seeds, "n_cases": len(cases), "n_by_type": n_by_type,
              "collapse_5_to_3": _COLLAPSE_5_TO_3, "summary": summary,
              "sample_rows": {"three_way": last_rows["three_way"], "five_way": last_rows["five_way"]}}
    json.dump(report, open(_REPORT, "w"), indent=2)

    print(f"\n===== ADVERSARIAL STANCE: 3-way vs 5-way (n={len(cases)} cases, {n_seeds} seeds) =====")
    print(f"{'failure type':26s} {'3way LEVEL':>16s} {'5way LEVEL':>16s}   {'3way STANCE':>14s} {'5way STANCE':>14s}")
    for t in FAILURE_TYPES:
        s3, s5 = summary["three_way"][t], summary["five_way"][t]
        print(f"{t:26s} "
              f"{s3['level']['mean']:.0%} [{s3['level']['min']:.0%}-{s3['level']['max']:.0%}]".rjust(16),
              f"{s5['level']['mean']:.0%} [{s5['level']['min']:.0%}-{s5['level']['max']:.0%}]".rjust(16), "  ",
              f"{s3['stance']['mean']:.0%}".rjust(13),
              f"{s5['stance']['mean']:.0%}".rjust(13))
    o3, o5 = summary["three_way"]["overall"], summary["five_way"]["overall"]
    print(f"{'OVERALL':26s} {o3['level']['mean']:.0%}".rjust(43),
          f"{o5['level']['mean']:.0%}".rjust(16))
    print(f"Report → {_REPORT}")


if __name__ == "__main__":
    try:
        asyncio.run(_main())
    except KeyboardInterrupt:
        print("\nAborted — no further calls.")
