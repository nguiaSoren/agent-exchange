"""CORRECTED gifted-span study — long multi-clause docs + weaker judges.

The atomic-snippet run (``spikes/gifted_span_run.py``) refuted the gate for two confounds:
no leak headroom (frontier judge already perfect) and genuine claims single-sourced (all
fail ablation → escalate-everything). This run removes both:

  * LONG, multi-clause contracts (``eval/long_corpus.py``) — a genuine finding can corroborate
    across spans (Definitions + clause + Survival restating the term), so it CAN survive
    ablation; a gifted-span lie hangs on one span and fails.
  * WEAKER judges (env ``WEAK_JUDGES``, default ``openai:gpt-4.1-mini`` + ``featherless:Qwen/Qwen2.5-72B-Instruct``)
    so there is leak headroom for the gate to close.

It measures, per (judge × config): gifted-span LEAK rate, genuine FALSE-ESCALATE rate, and —
the precondition the atomic corpus failed — the **genuine SUPPORTED-route fraction** (claims
that survive ablation). If that stays ~0 even on long docs, the finding is that substring
ablation is defeated by paraphrase (needs semantic ablation), not by document length.

Env (.env):
  - OPENAI_API_KEY / FEATHERLESS_API_KEY — for the providers used.
  - LONG_GEN_MODEL        — model to write the long contracts + claims (default gpt-4.1).
  - WEAK_JUDGES           — comma list of ``provider:model`` weak verifiers
                            (default ``openai:gpt-4.1-mini,featherless:Qwen/Qwen2.5-72B-Instruct``).
  - LONG_N_DOCS           — number of long contracts (default 4).
  - LONG_PER_DOC          — claims per class per doc (default 10).
Outputs: data/eval/long_contracts.json, long_doc_fixture.json, long_doc_report.json, long_doc_verdicts.json
"""

from __future__ import annotations

import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from dotenv import load_dotenv

from agent_exchange.core import make_backend
from agent_exchange.eval.gifted_span import GIFTED_SPAN, generate_gifted_span_for_docs
from agent_exchange.eval.long_corpus import (
    generate_genuine_claims,
    generate_long_contracts,
    load_long_contracts,
    save_long_contracts,
)
from agent_exchange.eval.payment_lens import (
    collect_verdicts,
    format_payment_report,
    score_payment_lens,
)
from agent_exchange.eval.seeded_liar import load_fixture, save_fixture
from agent_exchange.eval.types import GENUINE, LabeledClaim
from agent_exchange.verify import Verifier
from agent_exchange.verify.schema import DEFAULT_THRESHOLD, STRICT

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(_ROOT, ".env"))
_D = os.path.join(_ROOT, "data", "eval")
_CONTRACTS = os.path.join(_D, "long_contracts.json")
_FIXTURE = os.path.join(_D, "long_doc_fixture.json")
_REPORT = os.path.join(_D, "long_doc_report.json")
_VERDICTS = os.path.join(_D, "long_doc_verdicts.json")


def _class_to_dict(c) -> dict:
    return {k: getattr(c, k) for k in (
        "source", "is_fabricated", "n", "auto_paid", "escalated", "withheld", "partial_zero",
    )} | {k: getattr(c, k) for k in (
        "leak_rate", "contained_rate", "served_rate", "false_escalate_rate", "false_withhold_rate",
    )}


def _routes(pairs) -> dict:
    dist: dict[str, dict[str, int]] = {}
    for case, v in pairs:
        cls = case.source if case.label != GENUINE else GENUINE
        route = getattr(v, "deterministic_route", None) or "none"
        dist.setdefault(cls, {}).setdefault(route, 0)
        dist[cls][route] += 1
    return dist


async def _build_fixture(gen_model: str, n_docs: int, per_doc: int) -> tuple[list[str], list[LabeledClaim]]:
    # Long contracts: generate once, replay.
    if os.path.exists(_CONTRACTS):
        docs = load_long_contracts(_CONTRACTS)
        print(f"Loaded {len(docs)} long contracts from {_CONTRACTS}")
    else:
        print(f"Generating {n_docs} long contracts with {gen_model} (one-time)...")
        docs = await generate_long_contracts(make_backend("openai", gen_model), n=n_docs)
        save_long_contracts(docs, _CONTRACTS)
        print(f"  cached {len(docs)} → {_CONTRACTS}")
    # Mixed claims: generate once, replay.
    if os.path.exists(_FIXTURE):
        cases = load_fixture(_FIXTURE)
        print(f"Loaded {len(cases)} claims from {_FIXTURE}")
    else:
        print(f"Generating gifted-span + genuine claims ({per_doc}/class/doc) with {gen_model}...")
        gen_backend = make_backend("openai", gen_model)
        gifted = await generate_gifted_span_for_docs(gen_backend, docs, per_doc=per_doc)
        genuine = await generate_genuine_claims(gen_backend, docs, per_doc=per_doc)
        cases = list(gifted) + list(genuine)
        save_fixture(cases, _FIXTURE)
        print(f"  cached {len(cases)} ({len(gifted)} gifted / {len(genuine)} genuine) → {_FIXTURE}")
    return docs, cases


async def _main() -> None:
    if not (os.getenv("OPENAI_API_KEY") or "").strip():
        print("OPENAI_API_KEY not set — exiting, no spend.")
        return
    gen_model = os.getenv("LONG_GEN_MODEL", "gpt-4.1")
    judges = [j.strip() for j in os.getenv(
        "WEAK_JUDGES", "openai:gpt-4.1-mini,featherless:Qwen/Qwen2.5-72B-Instruct"
    ).split(",") if j.strip()]
    n_docs = int(os.getenv("LONG_N_DOCS", "4"))
    per_doc = int(os.getenv("LONG_PER_DOC", "10"))

    docs, cases = await _build_fixture(gen_model, n_docs, per_doc)
    n_gs = sum(c.source == GIFTED_SPAN for c in cases)
    n_gen = sum(c.label == GENUINE for c in cases)
    print(f"\nMixed long-doc fixture: {len(cases)} claims — {n_gs} gifted-span / {n_gen} genuine over {len(docs)} docs.\n")
    if not n_gs or not n_gen:
        print("Fixture missing a class; aborting.")
        return

    report = {
        "gen_model": gen_model, "n_docs": len(docs), "n_gifted_span": n_gs, "n_genuine": n_gen,
        "threshold": DEFAULT_THRESHOLD, "policy": STRICT.name, "judges": {},
    }
    verdict_dump: dict = {}

    for judge in judges:
        provider, _, model = judge.partition(":")
        if not (os.getenv({"openai": "OPENAI_API_KEY", "featherless": "FEATHERLESS_API_KEY",
                           "aimlapi": "AIMLAPI_API_KEY"}.get(provider, "OPENAI_API_KEY")) or "").strip():
            print(f"[skip judge {judge}] provider key not set")
            continue
        print("#" * 70 + f"\n# JUDGE: {judge}\n" + "#" * 70)
        configs = {
            "judge_only": Verifier(make_backend(provider, model)),
            "gate_teeth_off": Verifier(make_backend(provider, model), ablation_gate=True),
            "gate_teeth_on": Verifier(make_backend(provider, model), ablation_gate=True, escalate_single_sourced=True),
        }
        report["judges"][judge] = {"configs": {}, "route_distribution": {}}
        verdict_dump[judge] = {}
        for name, verifier in configs.items():
            try:
                pairs = await collect_verdicts(cases, verifier)
            except Exception as exc:  # noqa: BLE001 — one judge dying must not abort the rest
                print(f"  [judge {judge} / {name}] verify failed: {type(exc).__name__}: {exc}")
                continue
            rep = score_payment_lens(pairs, config=name, threshold=DEFAULT_THRESHOLD, policy=STRICT)
            print(format_payment_report(rep) + "\n")
            report["judges"][judge]["configs"][name] = {"classes": [_class_to_dict(c) for c in rep.classes]}
            report["judges"][judge]["route_distribution"][name] = _routes(pairs)
            verdict_dump[judge][name] = [
                {"source": (c.source if c.label != GENUINE else GENUINE), "label": c.label,
                 "claim": c.claim, "verdict": v.verdict.value, "confidence": v.confidence,
                 "route": getattr(v, "deterministic_route", None),
                 "ablation_survived": getattr(v, "deterministic_ablation_survived", None),
                 "escalated": v.needs_human(DEFAULT_THRESHOLD)}
                for c, v in pairs
            ]

    with open(_REPORT, "w") as f:
        json.dump(report, f, indent=2)
    with open(_VERDICTS, "w") as f:
        json.dump(verdict_dump, f, indent=2)
    print(f"Report → {_REPORT}\nVerdicts → {_VERDICTS}")

    # Headline per judge.
    print("\n=== HEADLINE (long docs) ===")
    for judge, jd in report["judges"].items():
        def g(cfg, src, attr):
            for c in jd["configs"].get(cfg, {}).get("classes", []):
                if c["source"] == src:
                    return c[attr]
            return None
        rd = jd["route_distribution"].get("gate_teeth_on", {}).get(GENUINE, {})
        sup = rd.get("supported", 0); tot = sum(rd.values()) or 1
        print(f"[{judge}]")
        print(f"  gifted-span LEAK:  judge_only {g('judge_only','llm_gifted_span','leak_rate')} → teeth_on {g('gate_teeth_on','llm_gifted_span','leak_rate')}")
        print(f"  genuine SUPPORTED-route fraction (precondition): {sup}/{tot} = {sup/tot:.0%}")
        print(f"  genuine FALSE-ESCALATE under teeth_on: {g('gate_teeth_on','genuine','false_escalate_rate')}")


if __name__ == "__main__":
    try:
        asyncio.run(_main())
    except KeyboardInterrupt:
        print("\nAborted — no further calls.")
