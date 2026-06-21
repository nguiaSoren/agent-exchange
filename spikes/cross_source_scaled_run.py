"""PAPER-GRADE scaled cross-source verification — contracts + heterogeneous facts, multi-seed.

The small slice (``cross_source_slice_run.py``) measured the StanceCrossSourceVerifier on 9 claims
/ 3 contracts and got 100%. This run scales it to paper grade across BOTH cross-source regimes:

  (a) CONTRACTS  — controlled construction: each long contract paired with a faithful restatement
      and an amendment that flips two terms → [AGREEMENT, SUMMARY, AMENDMENT] (cross_source.py).
  (b) HETEROGENEOUS facts — the harder, realistic PARALLAX shape: the SAME facts reported by 2-4
      INDEPENDENT documents of different styles (news brief / spec sheet / memo / notice), with
      built-in agreement, divergence, and fabricated claims (heterogeneous_corpus.py).

For each regime we run the StanceCrossSourceVerifier (support/contradict/silent — the correct one)
and score the corroboration LEVEL against each claim's intended label, OVERALL and PER-LABEL. We
repeat over >=3 SEEDS that shuffle claim order and source order (the only randomness that touches
the verifier), and report mean +/- spread (min..max) per label. We also compute a MONEY-LENS:
does any FABRICATED claim get a source to 'support' it (n_confirming >= 1)? — an auto-corroboration
of a lie is the cross-source analogue of a leaked payment.

Corpora are cached to data/eval/*corpus*.json so re-runs don't regenerate. Report:
data/eval/cross_source_scaled_report.json.

Env:
  GEN_MODEL    (default gpt-4.1)       — corpus generator
  CROSS_JUDGE  (default gpt-4.1-mini)  — the per-source stance judge
  N_CONTRACTS  (default 14)            — contracts to generate
  N_FACTSETS   (default 12)            — heterogeneous fact-sets to generate
  SEEDS        (default "0,1,2")       — order-shuffle seeds
"""

from __future__ import annotations

import asyncio
import json
import os
import random
import statistics
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from dotenv import load_dotenv

from agent_exchange.core import make_backend
from agent_exchange.eval.cross_source import (
    build_three_source_set,
    generate_amendment_and_claims,
    generate_contracts_corpus,
    generate_restatement,
)
from agent_exchange.eval.heterogeneous_corpus import (
    LABELS,
    factset_sources,
    generate_heterogeneous_corpus,
    load_corpus as load_hetero,
    save_corpus as save_hetero,
)
from agent_exchange.verify.cross_source_verifier import (
    Corroboration,
    StanceCrossSourceVerifier,
)

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(_ROOT, ".env"))
_EVAL = os.path.join(_ROOT, "data", "eval")
_CONTRACTS_CORPUS = os.path.join(_EVAL, "cross_source_contracts_corpus.json")
_HETERO_CORPUS = os.path.join(_EVAL, "heterogeneous_corpus.json")
_REPORT = os.path.join(_EVAL, "cross_source_scaled_report.json")

# A claim's intended label maps to the corroboration level we expect the verifier to assign.
_EXPECT = {
    "corroborated": {Corroboration.CORROBORATED},
    "divergent": {Corroboration.DIVERGENT},
    "fabricated": {Corroboration.UNCORROBORATED},
}


# --------------------------------------------------------------------------- #
# Corpus build / cache                                                        #
# --------------------------------------------------------------------------- #
async def _build_contracts_corpus(gen_model: str) -> list[dict]:
    """Each item: {sources: [(label,text)], claims: [{text,label}]}. Cached to disk."""
    if os.path.exists(_CONTRACTS_CORPUS):
        data = json.load(open(_CONTRACTS_CORPUS))
        return data["sets"]
    n = int(os.getenv("N_CONTRACTS", "14"))
    gb = make_backend("openai", gen_model)
    print(f"[contracts] generating {n} distinct long contracts with {gen_model}...")
    contracts = await generate_contracts_corpus(gb, n=n, seed=1)
    print(f"[contracts] generated {len(contracts)} contracts; building restatements + amendments...")
    sets: list[dict] = []
    for idx, contract in enumerate(contracts):
        summary = await generate_restatement(gb, contract)
        aset = await generate_amendment_and_claims(gb, contract)
        if not aset or not aset.get("claims"):
            print(f"[contracts]  doc {idx}: amendment/claims failed — skipped")
            continue
        sources = build_three_source_set(contract, summary, aset["amendment"])
        sets.append({"sources": sources, "claims": aset["claims"]})
        print(f"[contracts]  doc {idx}: {len(aset['claims'])} claims")
    json.dump({"sets": sets}, open(_CONTRACTS_CORPUS, "w"), indent=2, ensure_ascii=False)
    print(f"[contracts] froze {len(sets)} sets → {_CONTRACTS_CORPUS}")
    return sets


async def _build_hetero_corpus(gen_model: str) -> list[dict]:
    """Each item: a validated fact-set {topic, documents, claims}. Cached to disk."""
    if os.path.exists(_HETERO_CORPUS):
        return load_hetero(_HETERO_CORPUS)
    n = int(os.getenv("N_FACTSETS", "12"))
    gb = make_backend("openai", gen_model)
    print(f"[hetero] generating {n} heterogeneous fact-sets with {gen_model}...")
    factsets = await generate_heterogeneous_corpus(gb, n=n, n_docs=3)
    save_hetero(factsets, _HETERO_CORPUS)
    print(f"[hetero] froze {len(factsets)} fact-sets → {_HETERO_CORPUS}")
    return factsets


# --------------------------------------------------------------------------- #
# Scoring                                                                     #
# --------------------------------------------------------------------------- #
async def _score_one_seed(
    csv: StanceCrossSourceVerifier,
    items: list[tuple[list[tuple[str, str]], list[dict]]],
    seed: int,
) -> dict:
    """Run the verifier over every (sources, claims) item with claim+source order shuffled by seed.

    Returns {'overall': acc, 'by_label': {lab: acc}, 'leaks': n_fabricated_with_a_supporting_source,
             'n': total_claims, 'rows': [...]}.
    """
    rng = random.Random(seed)
    correct = 0
    total = 0
    by_label = {lab: {"n": 0, "ok": 0} for lab in LABELS}
    leaks = 0  # fabricated claims a source 'supported' (n_confirming >= 1)
    rows: list[dict] = []
    for sources, claims in items:
        srcs = list(sources)
        rng.shuffle(srcs)
        order = list(range(len(claims)))
        rng.shuffle(order)
        shuffled = [claims[i] for i in order]
        texts = [c["text"] for c in shuffled]
        labels = [c["label"] for c in shuffled]
        results = await csv.verify_claims(texts, srcs)
        for label, r in zip(labels, results):
            if label not in by_label:
                continue
            ok = r.level in _EXPECT.get(label, set())
            total += 1
            correct += ok
            by_label[label]["n"] += 1
            by_label[label]["ok"] += ok
            if label == "fabricated" and r.n_confirming >= 1:
                leaks += 1
            rows.append({
                "label": label, "level": r.level.value, "match": bool(ok),
                "n_confirming": r.n_confirming, "n_rejecting": r.n_rejecting,
                "claim": r.claim[:90],
            })
    return {
        "overall": correct / total if total else 0.0,
        "by_label": {lab: (v["ok"] / v["n"] if v["n"] else None) for lab, v in by_label.items()},
        "label_n": {lab: v["n"] for lab, v in by_label.items()},
        "leaks": leaks,
        "n": total,
        "rows": rows,
    }


def _aggregate_seeds(per_seed: list[dict]) -> dict:
    """Mean +/- spread (min..max) across seeds, overall and per label."""
    overalls = [s["overall"] for s in per_seed]
    agg = {
        "overall": {
            "mean": statistics.fmean(overalls),
            "min": min(overalls),
            "max": max(overalls),
        },
        "by_label": {},
        "leaks_per_seed": [s["leaks"] for s in per_seed],
        "n_claims": per_seed[0]["n"] if per_seed else 0,
        "label_n": per_seed[0]["label_n"] if per_seed else {},
    }
    for lab in LABELS:
        vals = [s["by_label"][lab] for s in per_seed if s["by_label"].get(lab) is not None]
        if vals:
            agg["by_label"][lab] = {
                "mean": statistics.fmean(vals), "min": min(vals), "max": max(vals),
            }
        else:
            agg["by_label"][lab] = None
    return agg


def _print_block(name: str, agg: dict) -> None:
    o = agg["overall"]
    print(f"\n=== {name} === (n={agg['n_claims']} claims/seed, {len(agg['leaks_per_seed'])} seeds)")
    print(f"  overall: {o['mean']:.1%}  (spread {o['min']:.1%}..{o['max']:.1%})")
    for lab in LABELS:
        b = agg["by_label"].get(lab)
        n = agg["label_n"].get(lab, 0)
        if b is None:
            print(f"  {lab:13s}: n=0 (none in corpus)")
        else:
            print(f"  {lab:13s}: {b['mean']:.1%}  (spread {b['min']:.1%}..{b['max']:.1%})  n={n}")
    print(f"  money-lens (fabricated claims a source SUPPORTED): {agg['leaks_per_seed']} per seed")


async def _main() -> None:
    if not (os.getenv("OPENAI_API_KEY") or "").strip():
        print("OPENAI_API_KEY not set — exiting.")
        return
    gen_model = os.getenv("GEN_MODEL", "gpt-4.1")
    judge_model = os.getenv("CROSS_JUDGE", "gpt-4.1-mini")
    seeds = [int(x) for x in os.getenv("SEEDS", "0,1,2").split(",") if x.strip()]

    contracts_sets = await _build_contracts_corpus(gen_model)
    hetero_sets = await _build_hetero_corpus(gen_model)

    # Normalize both regimes to the same shape: list of (sources, claims).
    contracts_items = [
        ([tuple(s) for s in item["sources"]], item["claims"]) for item in contracts_sets
    ]
    hetero_items = [(factset_sources(fs), fs["claims"]) for fs in hetero_sets]

    csv = StanceCrossSourceVerifier(make_backend("openai", judge_model))

    report: dict = {"judge": judge_model, "generator": gen_model, "mode": "stance", "seeds": seeds}
    for name, items in (("contracts", contracts_items), ("heterogeneous", hetero_items)):
        print(f"\n##### regime: {name}  ({len(items)} fact-sets) #####")
        per_seed = []
        for sd in seeds:
            res = await _score_one_seed(csv, items, sd)
            per_seed.append(res)
            print(f"  seed {sd}: overall {res['overall']:.1%}  leaks={res['leaks']}  n={res['n']}")
        agg = _aggregate_seeds(per_seed)
        agg["n_factsets"] = len(items)
        agg["per_seed"] = [
            {"seed": sd, "overall": s["overall"], "leaks": s["leaks"], "by_label": s["by_label"]}
            for sd, s in zip(seeds, per_seed)
        ]
        # keep one seed's rows for inspection
        agg["sample_rows"] = per_seed[0]["rows"]
        report[name] = agg
        _print_block(name, agg)

    json.dump(report, open(_REPORT, "w"), indent=2, ensure_ascii=False)
    print(f"\nReport → {_REPORT}")


if __name__ == "__main__":
    try:
        asyncio.run(_main())
    except KeyboardInterrupt:
        print("\nAborted — no further calls.")
