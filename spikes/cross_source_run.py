"""LIVE cross-source test — does ablation finally discriminate when claims are multi-sourced?

Axis (b): the regime where ablation's premise might hold. For each long contract we build a
SOURCE SET = [original + an independent restatement of its key terms], so a genuine claim is
corroborated across BOTH sources and a gifted-span mutation is contradicted by both. We verify
the existing genuine + gifted-span claims against the source set and re-test ablation:

  * JUDGE sufficiency: catch-rate / leak on the multi-source doc (is the judge still enough?).
  * ABLATION in this regime: of confirmed/partial genuine claims, what fraction SURVIVE
    ablation now — under lexical (substring) AND LLM-entailment? The hypothesis: genuine
    survival RISES well above the single-source 12%(lexical)/4%(llm), because the cited span in
    SOURCE 1 can be ablated and the claim still grounds in SOURCE 2 — validating ablation for
    cross-source verification (where single-source experiments said it was useless).

Env: OPENAI_API_KEY; CROSS_JUDGE (default gpt-4.1-mini); GEN_MODEL (default gpt-4.1).
Output: data/eval/cross_source_summaries.json, data/eval/cross_source_report.json.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from dotenv import load_dotenv

from agent_exchange.core import make_backend
from agent_exchange.eval.cross_source import build_source_set, generate_restatement
from agent_exchange.eval.long_corpus import load_long_contracts
from agent_exchange.eval.payment_lens import collect_verdicts
from agent_exchange.eval.seeded_liar import load_fixture
from agent_exchange.eval.types import FABRICATED, GENUINE
from agent_exchange.verify import Verdict, Verifier
from agent_exchange.verify.schema import DEFAULT_THRESHOLD
from agent_exchange.verify.semantic_ablation import survives_llm

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(_ROOT, ".env"))
_CONTRACTS = os.path.join(_ROOT, "data", "eval", "long_contracts.json")
_FIXTURE = os.path.join(_ROOT, "data", "eval", "long_doc_fixture.json")
_SUMMARIES = os.path.join(_ROOT, "data", "eval", "cross_source_summaries.json")
_REPORT = os.path.join(_ROOT, "data", "eval", "cross_source_report.json")


async def _main() -> None:
    if not (os.getenv("OPENAI_API_KEY") or "").strip():
        print("OPENAI_API_KEY not set — exiting, no spend.")
        return
    judge_model = os.getenv("CROSS_JUDGE", "gpt-4.1-mini")
    gen_model = os.getenv("GEN_MODEL", "gpt-4.1")
    contracts = load_long_contracts(_CONTRACTS)
    cases = load_fixture(_FIXTURE)

    # Restatements (the 2nd source), generate once, cache.
    if os.path.exists(_SUMMARIES):
        summaries = json.load(open(_SUMMARIES))["summaries"]
    else:
        print(f"Generating {len(contracts)} restatements with {gen_model} (one-time)...")
        gb = make_backend("openai", gen_model)
        summaries = [await generate_restatement(gb, c) for c in contracts]
        json.dump({"summaries": summaries}, open(_SUMMARIES, "w"), indent=2)
        print(f"  cached → {_SUMMARIES}")

    src_set = {c: build_source_set(c, s) for c, s in zip(contracts, summaries)}
    # Re-key each claim onto its contract's SOURCE SET (so verify runs against both sources).
    from agent_exchange.eval.types import LabeledClaim
    multi_cases = [LabeledClaim(src_set.get(c.contract, c.contract), c.claim, c.label, c.source)
                   for c in cases if c.contract in src_set]
    print(f"{len(multi_cases)} claims over {len(src_set)} source-sets (avg ~{sum(len(d.split()) for d in src_set.values())//max(1,len(src_set))} words/set)\n")

    backend = make_backend("openai", judge_model)
    pairs = await collect_verdicts(multi_cases, Verifier(backend, ablation_gate=True))

    # Judge sufficiency (money lens): fabricated auto-paid = leak.
    def auto_pays(v):
        return v.verdict is Verdict.CONFIRMED and v.confidence >= DEFAULT_THRESHOLD and not v.needs_human(DEFAULT_THRESHOLD)
    gifted = [(c, v) for c, v in pairs if c.label == FABRICATED]
    genuine = [(c, v) for c, v in pairs if c.label == GENUINE]
    gifted_leak = sum(auto_pays(v) for _, v in gifted)
    genuine_served = sum(auto_pays(v) for _, v in genuine)

    # Ablation in this regime: of confirmed/partial genuine with a present quote, survival.
    reach_gen = [(c, v) for c, v in genuine if v.verdict is not Verdict.UNSUPPORTED and v.evidence_quote]
    reach_gif = [(c, v) for c, v in gifted if v.verdict is not Verdict.UNSUPPORTED and v.evidence_quote]
    gen_llm = await asyncio.gather(*[survives_llm(c.claim, v.evidence_quote, c.contract, backend=backend) for c, v in reach_gen])
    gif_llm = await asyncio.gather(*[survives_llm(c.claim, v.evidence_quote, c.contract, backend=backend) for c, v in reach_gif])

    def frac(num, den): return num / den if den else 0.0
    gen_lex = sum(1 for _, v in reach_gen if v.deterministic_ablation_survived)
    gif_lex = sum(1 for _, v in reach_gif if v.deterministic_ablation_survived)
    gen_llm_n = sum(1 for s in gen_llm if s.survived)
    gif_llm_n = sum(1 for s in gif_llm if s.survived)

    report = {
        "judge": judge_model, "n_genuine": len(genuine), "n_gifted": len(gifted),
        "judge_sufficiency": {"gifted_leak": gifted_leak, "gifted_leak_rate": frac(gifted_leak, len(gifted)),
                              "genuine_served": genuine_served, "genuine_served_rate": frac(genuine_served, len(genuine))},
        "ablation_cross_source": {
            "genuine_reached": len(reach_gen), "gifted_reached": len(reach_gif),
            "genuine_supported_lexical": frac(gen_lex, len(reach_gen)),
            "genuine_supported_llm": frac(gen_llm_n, len(reach_gen)),
            "gifted_supported_lexical": frac(gif_lex, len(reach_gif)),
            "gifted_supported_llm": frac(gif_llm_n, len(reach_gif)),
        },
        "single_source_baseline": {"genuine_supported_lexical": 0.125, "genuine_supported_llm": 0.04},
    }
    json.dump(report, open(_REPORT, "w"), indent=2)
    a = report["ablation_cross_source"]
    print("=== JUDGE SUFFICIENCY (multi-source) ===")
    print(f"  gifted leak: {gifted_leak}/{len(gifted)} ({report['judge_sufficiency']['gifted_leak_rate']:.0%}) | genuine served: {genuine_served}/{len(genuine)} ({report['judge_sufficiency']['genuine_served_rate']:.0%})")
    print("\n=== ABLATION IN CROSS-SOURCE REGIME (the hypothesis test) ===")
    print(f"  genuine SUPPORTED (survive ablation):  lexical {a['genuine_supported_lexical']:.0%} (single-source 12%)  |  LLM {a['genuine_supported_llm']:.0%} (single-source 4%)")
    print(f"  gifted  SUPPORTED (should be ~0):       lexical {a['gifted_supported_lexical']:.0%}  |  LLM {a['gifted_supported_llm']:.0%}")
    print(f"\nReport → {_REPORT}")
    print("\n=== READING ===")
    print("If genuine LLM-SUPPORTED rises far above 4% while gifted stays ~0 ⇒ ablation is VALIDATED for cross-source (not useless project-wide).")


if __name__ == "__main__":
    try:
        asyncio.run(_main())
    except KeyboardInterrupt:
        print("\nAborted — no further calls.")
