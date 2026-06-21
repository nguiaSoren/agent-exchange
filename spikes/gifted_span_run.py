"""LIVE gifted-span study — the experiment behind Paper A's core figure (F1).

Measures the ablation gate against the adversary it was actually designed to stop: the
GIFTED-SPAN attack (a claim that mis-states a clause that IS present, so a real span sits
there for the judge to wrongly cite). The absent-clause catch-rate (the headline 100%) does
NOT exercise the gate — those lies have no span to hide behind. This run does.

Three verifier configs over ONE frozen mixed fixture (gifted-span fabrications + genuine
claims), scored by the PAYMENT LENS (did auto-money move?), not just the unsupported label:

  1. judge_only       — Verifier(backend)                       (gate fully off)
  2. gate_teeth_off   — ablation_gate=True                      (annotations + ESCALATE-on-absent,
                                                                  but JUDGE route is annotate-only)
  3. gate_teeth_on    — ablation_gate + escalate_single_sourced (JUDGE route escalates single-
                                                                  sourced confirms — the gate's teeth)

The honest comparison the paper makes:
  * gifted-span LEAK rate (auto-pay on a lie): judge_only vs gate_teeth_on — does the gate cut it?
  * genuine FALSE-ESCALATE rate: the gate's cost (escalating genuine single-source quotes).
  * gate_teeth_off is the control that proves the gate is INERT on gifted-span until given teeth
    (so any movement is the teeth, not the annotations).

Env contract (read from `.env`, mirrors catch_rate_run.py):
  - OPENAI_API_KEY            — required (generation + verification). Unset ⇒ print + exit, no spend.
  - OPENAI_VERIFIER_MODEL     — verifier model (default gpt-4.1; the trust anchor gets the strong model).
  - OPENAI_GEN_MODEL          — gifted-span generator model (default gpt-4.1-mini).
  - GIFTED_SPAN_N             — target gifted-span fabrications to generate (default 80).
  - GIFTED_SPAN_FIXTURE       — fixture path (default data/eval/gifted_span_fixture.json); generated once, replayed.
  - SEEDED_LIAR_FIXTURE       — source of genuine claims to fold in (default data/eval/seeded_liar_fixture.json).

Outputs:
  - data/eval/gifted_span_report.json    — per-config, per-class payment outcomes + route distribution (for figs).
  - data/eval/gifted_span_verdicts.json  — per-claim verdicts (label, source, verdict, conf, route, escalated) — re-scorable.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from dotenv import load_dotenv

from agent_exchange.core import make_backend
from agent_exchange.eval.gifted_span import GIFTED_SPAN, generate_gifted_span_claims
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

_GIFTED_FIXTURE = os.path.join(_ROOT, "data", "eval", "gifted_span_fixture.json")
_GENUINE_SRC = os.path.join(_ROOT, "data", "eval", "seeded_liar_fixture.json")
_REPORT = os.path.join(_ROOT, "data", "eval", "gifted_span_report.json")
_VERDICTS = os.path.join(_ROOT, "data", "eval", "gifted_span_verdicts.json")


def _class_to_dict(c) -> dict:
    return {
        "source": c.source,
        "is_fabricated": c.is_fabricated,
        "n": c.n,
        "auto_paid": c.auto_paid,
        "escalated": c.escalated,
        "withheld": c.withheld,
        "partial_zero": c.partial_zero,
        "leak_rate": c.leak_rate,
        "contained_rate": c.contained_rate,
        "served_rate": c.served_rate,
        "false_escalate_rate": c.false_escalate_rate,
        "false_withhold_rate": c.false_withhold_rate,
    }


def _route_distribution(pairs) -> dict:
    """Count gate routes by class (only meaningful when the ablation gate annotated them)."""
    dist: dict[str, dict[str, int]] = {}
    for case, v in pairs:
        cls = case.source if case.label != GENUINE else GENUINE
        route = getattr(v, "deterministic_route", None) or "none"
        dist.setdefault(cls, {}).setdefault(route, 0)
        dist[cls][route] += 1
    return dist


async def _main() -> None:
    if not (os.getenv("OPENAI_API_KEY") or "").strip():
        print("OPENAI_API_KEY not set — gifted-span run needs a model provider. Exiting, no spend.")
        return

    verifier_model = os.getenv("OPENAI_VERIFIER_MODEL", "gpt-4.1")
    gen_model = os.getenv("OPENAI_GEN_MODEL", "gpt-4.1-mini")
    n_target = int(os.getenv("GIFTED_SPAN_N", "80"))
    gifted_path = os.getenv("GIFTED_SPAN_FIXTURE", _GIFTED_FIXTURE)
    genuine_src = os.getenv("SEEDED_LIAR_FIXTURE", _GENUINE_SRC)

    # 1. gifted-span fabrications: generate once, replay.
    if os.path.exists(gifted_path):
        gifted = [c for c in load_fixture(gifted_path) if c.source == GIFTED_SPAN]
        print(f"Loaded {len(gifted)} gifted-span claims from {gifted_path}")
    else:
        print(f"Generating {n_target} gifted-span claims with {gen_model} (one-time)...")
        gifted = await generate_gifted_span_claims(make_backend("openai", gen_model), n_target=n_target)
        os.makedirs(os.path.dirname(gifted_path) or ".", exist_ok=True)
        save_fixture(gifted, gifted_path)
        print(f"  generated + cached {len(gifted)} → {gifted_path}")

    # 2. genuine claims to fold in (the false-escalate denominator), balanced to the gifted count.
    genuine_all = [c for c in load_fixture(genuine_src) if c.label == GENUINE] if os.path.exists(genuine_src) else []
    genuine = genuine_all[: len(gifted)]
    cases: list[LabeledClaim] = list(gifted) + list(genuine)
    print(f"\nMixed fixture: {len(cases)} claims — {len(gifted)} gifted-span / {len(genuine)} genuine.")
    if not gifted:
        print("No gifted-span claims generated; aborting.")
        return

    configs = {
        "judge_only": Verifier(make_backend("openai", verifier_model)),
        "gate_teeth_off": Verifier(make_backend("openai", verifier_model), ablation_gate=True),
        "gate_teeth_on": Verifier(
            make_backend("openai", verifier_model), ablation_gate=True, escalate_single_sourced=True
        ),
    }
    print(f"Running {len(configs)} configs × ~{len(cases)} claims with verifier {verifier_model}. Spends real money. Ctrl-C to abort.\n")

    report = {
        "verifier_model": verifier_model,
        "gen_model": gen_model,
        "n_gifted_span": len(gifted),
        "n_genuine": len(genuine),
        "threshold": DEFAULT_THRESHOLD,
        "policy": STRICT.name,
        "configs": {},
        "route_distribution": {},
    }
    verdict_dump: dict[str, list] = {}

    for name, verifier in configs.items():
        pairs = await collect_verdicts(cases, verifier)
        rep = score_payment_lens(pairs, config=name, threshold=DEFAULT_THRESHOLD, policy=STRICT)
        print(format_payment_report(rep) + "\n")
        report["configs"][name] = {"classes": [_class_to_dict(c) for c in rep.classes]}
        report["route_distribution"][name] = _route_distribution(pairs)
        verdict_dump[name] = [
            {
                "source": case.source if case.label != GENUINE else GENUINE,
                "label": case.label,
                "claim": case.claim,
                "verdict": v.verdict.value,
                "confidence": v.confidence,
                "route": getattr(v, "deterministic_route", None),
                "ablation_survived": getattr(v, "deterministic_ablation_survived", None),
                "escalated": v.needs_human(DEFAULT_THRESHOLD),
                "evidence_quote": v.evidence_quote,
            }
            for case, v in pairs
        ]

    os.makedirs(os.path.dirname(_REPORT) or ".", exist_ok=True)
    with open(_REPORT, "w") as f:
        json.dump(report, f, indent=2)
    with open(_VERDICTS, "w") as f:
        json.dump(verdict_dump, f, indent=2)
    print(f"Report → {_REPORT}\nPer-claim verdicts → {_VERDICTS}")

    # Headline diff for the console.
    jo = next(c for c in report["configs"]["judge_only"]["classes"] if c["source"] == GIFTED_SPAN)
    on = next(c for c in report["configs"]["gate_teeth_on"]["classes"] if c["source"] == GIFTED_SPAN)
    gen_on = next((c for c in report["configs"]["gate_teeth_on"]["classes"] if c["source"] == GENUINE), None)
    print("\n=== HEADLINE ===")
    print(f"gifted-span LEAK rate: judge_only {jo['leak_rate']:.1%} → gate_teeth_on {on['leak_rate']:.1%}")
    if gen_on:
        print(f"cost — genuine false-escalate under gate_teeth_on: {gen_on['false_escalate_rate']:.1%}")


if __name__ == "__main__":
    try:
        asyncio.run(_main())
    except KeyboardInterrupt:
        print("\nAborted by user — no further calls made.")
