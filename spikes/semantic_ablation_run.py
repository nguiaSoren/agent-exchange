"""Semantic ablation prototype — does a MEANING check fix F-D (genuine over-escalation)?

Finding F-D: lexical (substring) ablation rejects paraphrased genuine findings, so the gate
over-escalates honest work (genuine SUPPORTED-route fraction 12.5% even on long docs). This
run tests whether a SEMANTIC residual-support check rescues them — and whether it stays
sensitive to the numeric/scope mutations gifted-span uses (the embedding pre-check showed
cos("72h","24h")=0.971, so embeddings are suspect).

Two measurements on the frozen long-doc fixture (no new generation), judge = gpt-4.1-mini:

PART A — DISCRIMINATION PROBE (no ablation; can the signal tell truth from a mutated lie?):
  for every claim vs the FULL document — embedding max-cosine, and LLM entailment. A good
  signal scores genuine HIGH and gifted-span LOW. Expectation: embeddings high for BOTH (no
  separation); LLM separates.

PART B — GATE INTEGRATION (with ablation; the SUPPORTED-route fraction the gate would give):
  re-run the judge to get its real cited quotes, then for each confirmed/partial claim with a
  present quote compute lexical / embedding / LLM survival → the genuine-rescue vs
  gifted-leak trade per method.

Env: OPENAI_API_KEY; SEM_JUDGE (default gpt-4.1-mini); EMBED_MODEL (default text-embedding-3-small);
     SEM_TAU (default 0.62). Output: data/eval/semantic_ablation_report.json.
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
from agent_exchange.eval.payment_lens import collect_verdicts
from agent_exchange.eval.seeded_liar import load_fixture
from agent_exchange.eval.types import FABRICATED, GENUINE
from agent_exchange.verify import Verdict, Verifier
from agent_exchange.verify.embeddings import cosine, make_embedder, sentence_split
from agent_exchange.verify.semantic_ablation import (
    build_entailment_messages,
    survives_embedding,
    survives_llm,
)

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(_ROOT, ".env"))
_FIXTURE = os.path.join(_ROOT, "data", "eval", "long_doc_fixture.json")
_REPORT = os.path.join(_ROOT, "data", "eval", "semantic_ablation_report.json")


def _mean(xs):
    xs = list(xs)
    return sum(xs) / len(xs) if xs else 0.0


async def _entail_full_doc(backend, claim: str, document: str, sem: asyncio.Semaphore) -> tuple[bool, float]:
    """Direct entailment: is the claim supported by the FULL document? (Part A probe.)"""
    system = (
        "Decide whether a CLAIM is supported by a DOCUMENT, using ONLY the document. Be "
        "strict about numbers, durations, and scope (a claim of '24 hours' is NOT supported "
        'by text saying \'72 hours\'). Output ONLY JSON: {"supported": true|false, "confidence": 0..1}.'
    )
    user = f'DOCUMENT:\n"""\n{document.strip()}\n"""\n\nCLAIM: {claim.strip()}\n\nReturn the JSON now.'
    async with sem:
        r = await backend.complete([Message.system(system), Message.user(user)], temperature=0.0, max_tokens=120)
    import re
    m = re.search(r"\{.*\}", (r.text or ""), re.DOTALL)
    if not m:
        return (False, 0.0)
    try:
        o = json.loads(m.group(0))
        return (bool(o.get("supported", False)), float(o.get("confidence", 0.0)))
    except (json.JSONDecodeError, ValueError, TypeError):
        return (False, 0.0)


async def _main() -> None:
    if not (os.getenv("OPENAI_API_KEY") or "").strip():
        print("OPENAI_API_KEY not set — exiting, no spend.")
        return
    judge_model = os.getenv("SEM_JUDGE", "gpt-4.1-mini")
    embed_model = os.getenv("EMBED_MODEL", "text-embedding-3-small")
    tau = float(os.getenv("SEM_TAU", "0.62"))
    if not os.path.exists(_FIXTURE):
        print(f"Fixture missing: {_FIXTURE} — run spikes/long_doc_gate_run.py first.")
        return

    cases = load_fixture(_FIXTURE)
    docs = {}
    for c in cases:
        docs.setdefault(c.contract, True)
    print(f"Loaded {len(cases)} claims over {len(docs)} docs. judge={judge_model}, embed={embed_model}, tau={tau}\n")

    embedder = make_embedder("openai", embed_model)
    backend = make_backend("openai", judge_model)
    sem = asyncio.Semaphore(8)

    def embed_fn(texts):
        return embedder.embed(texts)

    # ---- PART A: discrimination probe (claim vs full doc) ----
    print("PART A — discrimination probe (claim vs FULL document)...")
    # Embedding: precompute doc-sentence vectors per doc; claim max-cosine to any sentence.
    doc_sents = {d: sentence_split(d) for d in docs}
    doc_vecs = {d: (embed_fn(s) if s else []) for d, s in doc_sents.items()}
    claim_vecs = embed_fn([c.claim for c in cases])
    probe = {"genuine": {"emb": [], "llm": []}, "gifted": {"emb": [], "llm": []}}
    entail = await asyncio.gather(*[_entail_full_doc(backend, c.claim, c.contract, sem) for c in cases])
    for c, cv, (suph, _conf) in zip(cases, claim_vecs, entail):
        bucket = "gifted" if c.label == FABRICATED else "genuine"
        best = max((cosine(cv, sv) for sv in doc_vecs[c.contract]), default=0.0)
        probe[bucket]["emb"].append(best)
        probe[bucket]["llm"].append(1.0 if suph else 0.0)

    def summ(b):
        e = probe[b]["emb"]; l = probe[b]["llm"]
        return {
            "n": len(e),
            "emb_mean_max_cosine": round(_mean(e), 3),
            "emb_frac_ge_tau": round(_mean([1.0 if x >= tau else 0.0 for x in e]), 3),
            "llm_frac_supported": round(_mean(l), 3),
        }
    partA = {"genuine": summ("genuine"), "gifted": summ("gifted")}
    print("  genuine:", partA["genuine"])
    print("  gifted :", partA["gifted"])

    # ---- PART B: gate integration (ablation, judge's real quotes) ----
    print("\nPART B — gate integration (judge quotes + ablation)...")
    pairs = await collect_verdicts(cases, Verifier(backend, ablation_gate=True))
    # Only confirmed/partial with a present quote reach the survival check.
    reach = [(c, v) for c, v in pairs if v.verdict is not Verdict.UNSUPPORTED and v.evidence_quote]
    partB = {"genuine": {"n": 0, "lexical": 0, "embedding": 0, "llm": 0},
             "gifted": {"n": 0, "lexical": 0, "embedding": 0, "llm": 0}}
    llm_surv = await asyncio.gather(*[
        survives_llm(c.claim, v.evidence_quote, c.contract, backend=backend) for c, v in reach
    ])
    for (c, v), ls in zip(reach, llm_surv):
        b = "gifted" if c.label == FABRICATED else "genuine"
        partB[b]["n"] += 1
        if v.deterministic_ablation_survived:
            partB[b]["lexical"] += 1
        es = survives_embedding(c.claim, v.evidence_quote, c.contract, embed_fn=embed_fn, tau=tau)
        if es.survived:
            partB[b]["embedding"] += 1
        if ls.survived:
            partB[b]["llm"] += 1
    for b in ("genuine", "gifted"):
        d = partB[b]; n = d["n"] or 1
        print(f"  {b}: reached={d['n']}  SUPPORTED-frac  lexical={d['lexical']/n:.0%}  embedding={d['embedding']/n:.0%}  llm={d['llm']/n:.0%}")

    report = {"judge": judge_model, "embed_model": embed_model, "tau": tau,
              "n_claims": len(cases), "n_docs": len(docs),
              "part_a_discrimination": partA, "part_b_gate": partB}
    with open(_REPORT, "w") as f:
        json.dump(report, f, indent=2)
    print(f"\nReport → {_REPORT}")
    print("\n=== READING ===")
    print("F-D fixable? genuine SUPPORTED should rise above lexical's ~12%.")
    print("New hole? gifted SUPPORTED / gifted emb_frac_ge_tau high ⇒ that semantic signal is fooled by the mutation.")


if __name__ == "__main__":
    try:
        asyncio.run(_main())
    except KeyboardInterrupt:
        print("\nAborted — no further calls.")
