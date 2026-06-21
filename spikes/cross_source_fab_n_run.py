"""F-I fabrication-arm at a real n — raise the gifted-span sample that reaches the ablation check.

The F-I positive result reported the fabrication arm at n=2 (only 2 of 20 gifted-span claims got
confirmed-with-a-quote and thus reached the ablation survival check; the judge caught the rest).
n=2 is "absence of a counterexample in too small a sample," not demonstrated discrimination. This
run raises that n: it generates MANY gifted-span claims (~120) and runs the SAME F-I pipeline —
verify against the 2-source set [agreement + restatement] (gpt-4.1-mini judge, ablation gate),
keep those that reach the check (confirmed/partial + present quote), and measure how many survive
ablation (lexical + LLM-entailment). The genuine arm (67%) is unchanged; this powers the
fabrication arm.

Deterministic where possible; the generation + verification are live (gpt-4.1-mini). Output:
data/eval/cross_source_fab_n_report.json. Env: OPENAI_API_KEY; CROSS_JUDGE (gpt-4.1-mini),
GEN_MODEL (gpt-4.1), GS_PER_DOC (default 30).
"""

from __future__ import annotations

import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from dotenv import load_dotenv

from agent_exchange.core import make_backend
from agent_exchange.core.types import Message
from agent_exchange.eval.cross_source import build_source_set
from agent_exchange.eval.gifted_span import _GIFTED_SPAN_SYSTEM
from agent_exchange.eval.long_corpus import load_long_contracts
from agent_exchange.eval.seeded_liar import _parse_claim_strings
from agent_exchange.verify import Verdict, Verifier
from agent_exchange.verify.semantic_ablation import survives_llm


async def _bulk_gifted(backend, doc, *, target=30):
    """Generate ~`target` DISTINCT gifted-span claims for one doc (multiple temp>0 calls, deduped).

    The shipped generator does one temp-0 call (~5 claims); to raise n we loop with temperature
    variation and a 'avoid repeating' nudge, accumulating distinct claims up to `target`.
    """
    seen: dict[str, bool] = {}
    out: list[str] = []
    for attempt in range(8):
        if len(out) >= target:
            break
        msgs = [Message.system(_GIFTED_SPAN_SYSTEM),
                Message.user(f"CONTRACT:\n\"\"\"\n{doc.strip()}\n\"\"\"\n\nReturn the JSON array of "
                             f"mis-stated claim strings now (variation {attempt+1}; avoid repeating earlier claims).")]
        res = await backend.complete(msgs, temperature=0.7, max_tokens=900)
        for s in _parse_claim_strings(res.text):
            k = s.strip().lower()
            if s.strip() and k not in seen:
                seen[k] = True
                out.append(s.strip())
    return out[:target]

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(_ROOT, ".env"))
_CONTRACTS = os.path.join(_ROOT, "data", "eval", "long_contracts.json")
_SUMMARIES = os.path.join(_ROOT, "data", "eval", "cross_source_summaries.json")
_GS_FIXTURE = os.path.join(_ROOT, "data", "eval", "cross_source_fab_n_fixture.json")
_REPORT = os.path.join(_ROOT, "data", "eval", "cross_source_fab_n_report.json")


async def _main() -> None:
    if not (os.getenv("OPENAI_API_KEY") or "").strip():
        print("OPENAI_API_KEY not set — exiting.")
        return
    judge_model = os.getenv("CROSS_JUDGE", "gpt-4.1-mini")
    gen_model = os.getenv("GEN_MODEL", "gpt-4.1")
    per_doc = int(os.getenv("GS_PER_DOC", "30"))
    contracts = load_long_contracts(_CONTRACTS)
    summaries = json.load(open(_SUMMARIES))["summaries"]
    src_sets = {c: build_source_set(c, s) for c, s in zip(contracts, summaries)}

    # Generate (or load) a LARGE gifted-span set: per_doc per contract.
    if os.path.exists(_GS_FIXTURE):
        gifted = json.load(open(_GS_FIXTURE))["claims"]  # [{contract_idx, claim}]
        print(f"Loaded {len(gifted)} gifted-span claims from cache")
    else:
        print(f"Bulk-generating ~{per_doc} gifted-span claims/doc with {gen_model}...")
        gb = make_backend("openai", gen_model)
        gifted = []
        for idx, c in enumerate(contracts):
            claims = await _bulk_gifted(gb, c, target=per_doc)
            print(f"  contract {idx}: {len(claims)} distinct gifted-span claims")
            gifted.extend({"contract_idx": idx, "claim": cl} for cl in claims)
        json.dump({"claims": gifted}, open(_GS_FIXTURE, "w"), indent=2)
        print(f"  cached {len(gifted)} → {_GS_FIXTURE}")

    judge = Verifier(make_backend("openai", judge_model), ablation_gate=True)
    # Group claims by contract, verify against that contract's 2-source set.
    by_doc: dict[int, list[str]] = {}
    for g in gifted:
        by_doc.setdefault(g["contract_idx"], []).append(g["claim"])

    n_gifted = len(gifted)
    reached = []  # (claim, source_set, verdict) for confirmed/partial + present quote
    for idx, claims in by_doc.items():
        src = src_sets[contracts[idx]]
        verdicts = await judge.verify(src, claims)
        for claim, v in zip(claims, verdicts):
            if v.verdict is not Verdict.UNSUPPORTED and v.evidence_quote:
                reached.append((claim, src, v))

    print(f"\n{n_gifted} gifted-span claims → {len(reached)} reached the ablation check "
          f"(confirmed/partial + present quote)")

    # Of those reaching, how many survive ablation (lexical + LLM-entailment)?
    lex_survived = sum(1 for _, _, v in reached if v.deterministic_ablation_survived)
    llm_results = await asyncio.gather(*[survives_llm(c, v.evidence_quote, src, backend=judge.backend)
                                         for c, src, v in reached])
    llm_survived = sum(1 for s in llm_results if s.survived)

    n_reach = len(reached)
    report = {
        "judge": judge_model, "gen_model": gen_model, "n_gifted": n_gifted,
        "n_reached": n_reach,
        "gifted_supported_lexical": round(lex_survived / n_reach, 4) if n_reach else 0.0,
        "gifted_supported_llm": round(llm_survived / n_reach, 4) if n_reach else 0.0,
        "lex_survived": lex_survived, "llm_survived": llm_survived,
        "baseline_F_I": {"n_reached": 2, "gifted_supported_llm": 0.0},
        "survived_claims_llm": [reached[i][0][:120] for i, s in enumerate(llm_results) if s.survived],
    }
    json.dump(report, open(_REPORT, "w"), indent=2)
    print(f"\n=== FABRICATION ARM (powered) ===")
    print(f"  reached check: {n_reach} (F-I baseline: 2)")
    print(f"  survive ablation — lexical: {lex_survived}/{n_reach} = {report['gifted_supported_lexical']:.0%}  "
          f"LLM-entailment: {llm_survived}/{n_reach} = {report['gifted_supported_llm']:.0%}")
    print(f"Report → {_REPORT}")


if __name__ == "__main__":
    try:
        asyncio.run(_main())
    except KeyboardInterrupt:
        print("\nAborted — no further calls.")
