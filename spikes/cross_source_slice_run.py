"""LIVE cross-source verification slice — corroboration & divergence across 3 sources.

The full slice for the PARALLAX job type (where ablation has a job, F-I). For each contract we
build a 3-source set [AGREEMENT, SUMMARY (restatement), AMENDMENT (changes 2 terms)] and a small
LABELED claim set:
  - corroborated : true, unchanged term            → expect CORROBORATED (≥2 sources confirm)
  - divergent    : original value of a CHANGED term → expect DIVERGENT (original+summary confirm, amendment rejects)
  - fabricated   : false                            → expect UNCORROBORATED

Runs `CrossSourceVerifier` and reports whether the corroboration level matches the intended
label — i.e. does cross-source verification correctly surface corroboration vs divergence vs
no-support? Output: data/eval/cross_source_slice_report.json.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from dotenv import load_dotenv

from agent_exchange.core import make_backend
from agent_exchange.eval.cross_source import (
    build_three_source_set,
    generate_amendment_and_claims,
    generate_restatement,
)
from agent_exchange.eval.long_corpus import load_long_contracts
from agent_exchange.verify import Verifier
from agent_exchange.verify.cross_source_verifier import (
    Corroboration,
    CrossSourceVerifier,
    StanceCrossSourceVerifier,
)

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(_ROOT, ".env"))
_CONTRACTS = os.path.join(_ROOT, "data", "eval", "long_contracts.json")
_SUMMARIES = os.path.join(_ROOT, "data", "eval", "cross_source_summaries.json")
_AMENDMENTS = os.path.join(_ROOT, "data", "eval", "cross_source_amendments.json")
_REPORT = os.path.join(_ROOT, "data", "eval", "cross_source_slice_report.json")

# Which corroboration level we EXPECT for each intended label.
_EXPECT = {
    "corroborated": {Corroboration.CORROBORATED},
    "divergent": {Corroboration.DIVERGENT},
    "fabricated": {Corroboration.UNCORROBORATED},
}


async def _main() -> None:
    if not (os.getenv("OPENAI_API_KEY") or "").strip():
        print("OPENAI_API_KEY not set — exiting.")
        return
    judge_model = os.getenv("CROSS_JUDGE", "gpt-4.1-mini")
    gen_model = os.getenv("GEN_MODEL", "gpt-4.1")
    n_docs = int(os.getenv("SLICE_N_DOCS", "3"))
    contracts = load_long_contracts(_CONTRACTS)[:n_docs]

    # restatements (reuse cross_source cache if present)
    if os.path.exists(_SUMMARIES):
        summaries = json.load(open(_SUMMARIES))["summaries"][:n_docs]
    else:
        gb = make_backend("openai", gen_model)
        summaries = [await generate_restatement(gb, c) for c in contracts]
        json.dump({"summaries": summaries}, open(_SUMMARIES, "w"), indent=2)

    # amendments + labeled claims (generate once, cache)
    if os.path.exists(_AMENDMENTS):
        amend = json.load(open(_AMENDMENTS))["sets"]
    else:
        print(f"Generating {len(contracts)} amendments + labeled claims with {gen_model}...")
        gb = make_backend("openai", gen_model)
        amend = [await generate_amendment_and_claims(gb, c) for c in contracts]
        json.dump({"sets": amend}, open(_AMENDMENTS, "w"), indent=2)

    mode = os.getenv("SLICE_MODE", "stance")  # 'stance' (fix) or 'confirm' (naive baseline)
    if mode == "stance":
        csv = StanceCrossSourceVerifier(make_backend("openai", judge_model))
    else:
        csv = CrossSourceVerifier(Verifier(make_backend("openai", judge_model)))
    print(f"Cross-source mode: {mode}")
    rows = []
    correct = 0
    total = 0
    by_label = {}
    for contract, summary, aset in zip(contracts, summaries, amend):
        if not aset or not aset.get("claims"):
            continue
        sources = build_three_source_set(contract, summary, aset["amendment"])
        claims = [c["text"] for c in aset["claims"]]
        labels = [c["label"] for c in aset["claims"]]
        results = await csv.verify_claims(claims, sources)
        for label, r in zip(labels, results):
            ok = r.level in _EXPECT.get(label, set())
            total += 1
            correct += ok
            by_label.setdefault(label, {"n": 0, "ok": 0})
            by_label[label]["n"] += 1
            by_label[label]["ok"] += ok
            rows.append({"label": label, "level": r.level.value, "match": ok,
                         "n_confirming": r.n_confirming, "n_rejecting": r.n_rejecting,
                         "per_source": [(s.label, s.verdict, s.confirms) for s in r.per_source],
                         "claim": r.claim[:90]})
            print(f"  [{'OK ' if ok else 'XX '}] label={label:12s} → {r.level.value:14s} (confirm={r.n_confirming} reject={r.n_rejecting})  {r.claim[:70]}")

    report = {"judge": judge_model, "mode": mode, "n_claims": total, "accuracy": (correct / total if total else 0.0),
              "by_label": {k: {"n": v["n"], "accuracy": v["ok"] / v["n"] if v["n"] else 0.0} for k, v in by_label.items()},
              "rows": rows}
    json.dump(report, open(_REPORT, "w"), indent=2)
    print(f"\nCross-source classification accuracy: {correct}/{total} = {report['accuracy']:.0%}")
    for k, v in report["by_label"].items():
        print(f"  {k}: {v['accuracy']:.0%} (n={v['n']})")
    print(f"Report → {_REPORT}")


if __name__ == "__main__":
    try:
        asyncio.run(_main())
    except KeyboardInterrupt:
        print("\nAborted — no further calls.")
