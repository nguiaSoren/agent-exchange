"""LIVE scaled adaptive adversary — bigger budget + DIVERSE attacker panel.

Scales the PAIR search: more rounds (default 12) and a PANEL of modern, cross-vendor attacker
models rotated per round, so the loop isn't bottlenecked by one model's blind spots. A breach
= TARGET auto-pays a claim the INDEPENDENT off-target ORACLE (a different vendor than the target)
marks false. The oracle is TIERED by cost: cheap sonnet-4.6 where it already dominates the target,
opus-4.8 only for the frontier target (a too-weak oracle would make "frontier 0 breaches"
meaningless). The configs form a judge-capability SPINE (targets weak→mid→frontier, climbing into
the gpt-5.5 generation) plus two cross-family robustness checks. ALL Anthropic calls are NATIVE
(provider "anthropic", DASHED model ids → prompt caching), so the oracle/checker are cheap.
  weak = gpt-5.4-nano (oracle claude-sonnet-4-6) · mid = gpt-5.4 (claude-sonnet-4-6)
  frontier = gpt-5.5 (claude-opus-4-8) · xcheck_anthropic = claude-sonnet-4-6 (oracle claude-opus-4-8)
  xcheck_openweight = qwen-2.5-72b (claude-sonnet-4-6)

A native-Anthropic FALSEHOOD CHECKER (claude-sonnet-4-6) pre-screens candidate claims by default
(SCALED_CHECK=1; set 0 to disable). Beyond the strict breach metric we surface SOFT-LEAKS (target
auto-pays AND >=1 oracle is partial-or-unsupported) and DOUBLE-CONFIRMS (target pays AND >=1 oracle
did not reject). A USAGE METER wraps every backend so per-config + grand-total token/cost are recorded.

Env: OPENAI_API_KEY + OPENROUTER_API_KEY + ANTHROPIC_API_KEY; SCALED_ROUNDS (default 12);
     SCALED_CONFIGS (default "weak,mid,frontier" — the spine; add the xcheck_* configs for the
     cross-family pass); SCALED_CONTRACTS (override the corpus path, e.g. the n=40 file);
     SCALED_CHECK (default "1" — native falsehood checker on); SCALED_CONCURRENCY (default 6 —
     global in-flight cap across all configs). Output: data/eval/scaled_adaptive_report.json,
     written incrementally after EACH config so a kill never loses completed work.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from dataclasses import asdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

# Line-buffer stdout so progress shows live even when redirected to a log file.
try:
    sys.stdout.reconfigure(line_buffering=True)
except (AttributeError, ValueError):
    pass

from dotenv import load_dotenv

from agent_exchange.core import make_backend
from agent_exchange.core.backend import ModelBackend
from agent_exchange.core.types import CompletionResult, Message
from agent_exchange.eval.adaptive_adversary import AdaptiveResult, run_adaptive_attack
from agent_exchange.eval.long_corpus import load_long_contracts
from agent_exchange.verify import Verifier

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(_ROOT, ".env"))
_CONTRACTS = os.getenv("SCALED_CONTRACTS") or os.path.join(_ROOT, "data", "eval", "long_contracts.json")
_REPORT = os.getenv("SCALED_REPORT") or os.path.join(_ROOT, "data", "eval", "scaled_adaptive_report.json")

# Global in-flight cap shared across ALL configs (running concurrently): total adaptive attacks
# in flight is bounded by this single semaphore, so cost/rate stays predictable (L5).
_GLOBAL_SEM = asyncio.Semaphore(int(os.getenv("SCALED_CONCURRENCY", "6")))

# Diverse, modern, cross-vendor attacker panel (rotated per round) — a stronger PAIR search.
# Anthropic is routed NATIVELY (dashed id → prompt caching).
_PANEL = [
    ("openai", "gpt-5.4"),
    ("anthropic", "claude-sonnet-4-6"),
    ("openrouter", "deepseek/deepseek-v3.2"),
]
# Ground-truth ORACLE per config: a breach = target auto-pays a claim the oracle rejects, so the
# oracle must be INDEPENDENT (different vendor → no collision) AND at least as strong as the target.
# We TIER it by cost: a cheap independent oracle (sonnet-4-6) wherever it already dominates the
# target (weak/mid), and a peer-or-stronger oracle (opus-4-8) ONLY for the frontier target —
# else "frontier 0 breaches" just means the oracle was too weak to out-judge it. Both are ORACLES,
# never judges under test. (To go cheaper still, swap sonnet-4-6 for qwen-2.5-72b under a judge
# rubric — your ROGUE judge-v3 idea — once it is sanity-checked on the contract task.)
_ORACLE_CHEAP = ("anthropic", "claude-sonnet-4-6")   # native, cheap (caching); dominates nano / gpt-5.4
_ORACLE_STRONG = ("anthropic", "claude-opus-4-8")    # native peer-or-stronger; only where the target is frontier
# Judge-capability spine (targets weak→mid→frontier, climbing into the gpt-5.5 generation)
# + two cross-family robustness checks.
_CONFIGS = {
    "weak":      (("openai", "gpt-5.4-nano"),       _ORACLE_CHEAP),
    "mid":       (("openai", "gpt-5.4"),            _ORACLE_CHEAP),
    "frontier":  (("openai", "gpt-5.5-2026-04-23"), _ORACLE_STRONG),
    "xcheck_anthropic":  (("anthropic", "claude-sonnet-4-6"),           _ORACLE_STRONG),
    "xcheck_openweight": (("openrouter", "qwen/qwen-2.5-72b-instruct"), _ORACLE_CHEAP),
}

_KEYMAP = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "aimlapi": "AIMLAPI_API_KEY",
    "featherless": "FEATHERLESS_API_KEY",
}


class UsageMeter(ModelBackend):
    """Drop-in wrapper: `await`s the inner backend's `.complete(...)` unchanged and accumulates
    usage into running totals. `run_adaptive_attack` and `Verifier` call `.complete(...)` exactly
    the same way, so this is transparent."""

    def __init__(self, inner: ModelBackend):
        self.inner = inner
        self.input_tokens = 0
        self.output_tokens = 0
        self.cached_input_tokens = 0
        self.est_cost_usd = 0.0

    async def complete(
        self,
        messages: list[Message],
        *,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> CompletionResult:
        result = await self.inner.complete(messages, temperature=temperature, max_tokens=max_tokens)
        u = result.usage
        self.input_tokens += u.input_tokens
        self.output_tokens += u.output_tokens
        self.cached_input_tokens += u.cached_input_tokens
        self.est_cost_usd += u.estimated_cost_usd or 0.0
        return result

    def totals(self) -> dict:
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cached_input_tokens": self.cached_input_tokens,
            "est_cost_usd": round(self.est_cost_usd, 6),
        }


def _sum_meters(meters: list[UsageMeter]) -> dict:
    return {
        "input_tokens": sum(m.input_tokens for m in meters),
        "output_tokens": sum(m.output_tokens for m in meters),
        "cached_input_tokens": sum(m.cached_input_tokens for m in meters),
        "est_cost_usd": round(sum(m.est_cost_usd for m in meters), 6),
    }


async def _run_config(name, docs, rounds) -> dict:
    (tp, tm), (op, om) = _CONFIGS[name]
    check_on = os.getenv("SCALED_CHECK", "1").strip() != "0"
    need = {tp, op} | {p for p, _ in _PANEL}
    if check_on:
        need.add("anthropic")  # native falsehood checker
    missing = [p for p in need if not (os.getenv(_KEYMAP.get(p, "")) or "").strip()]
    if missing:
        print(f"[skip {name}] missing keys: {missing}")
        return {"skipped": True, "missing": missing}

    print(f"\n{'='*64}\n# {name}: target={tp}:{tm} oracle={op}:{om} panel={[m for _,m in _PANEL]} "
          f"rounds={rounds} checker={'claude-sonnet-4-6' if check_on else 'off'}\n{'='*64}")

    # Wrap every backend in a UsageMeter (drop-in) so we capture real token/cost per config.
    target_m = UsageMeter(make_backend(tp, tm))
    oracle_m = UsageMeter(make_backend(op, om))
    panel_meters = [UsageMeter(make_backend(p, m)) for p, m in _PANEL]
    checker_m = UsageMeter(make_backend("anthropic", "claude-sonnet-4-6")) if check_on else None

    target = Verifier(target_m)
    oracle = Verifier(oracle_m)
    panel = panel_meters
    checker = checker_m

    async def _one(doc):
        async with _GLOBAL_SEM:
            try:
                return await run_adaptive_attack(
                    doc, target=target, oracle=oracle, attacker_panel=panel,
                    max_rounds=rounds, claim_checker=checker,
                )
            except Exception as e:  # one bad input/call must NOT cancel the doc, the config, or its siblings (L13)
                print(f"  [{name}] DOC ERRORED ({type(e).__name__}: {str(e)[:90]}) — skipped; run continues")
                return AdaptiveResult(document_preview=str(doc).strip()[:80], attempts=(), breached=False, rounds_used=0)

    results = await asyncio.gather(*[_one(d) for d in docs])
    n_breached = sum(r.breached for r in results)
    n_soft_leak = sum(a.soft_leak for r in results for a in r.attempts)
    n_double_confirm = sum(a.double_confirm for r in results for a in r.attempts)
    print(f"  [{name}] BREACHED {n_breached}/{len(results)} docs · soft-leaks {n_soft_leak} · "
          f"double-confirms {n_double_confirm} · {sum(r.rounds_used for r in results)} attempts")
    for r in results:
        if r.breached:
            for a in r.attempts:
                if a.breached:
                    print(f"    [{name}] BREACH [{a.strategy}] {r.document_preview!r}: {a.claim}")

    meters = [target_m, oracle_m, *panel_meters] + ([checker_m] if checker_m else [])
    cost = _sum_meters(meters)
    print(f"  [{name}] COST ${cost['est_cost_usd']:.4f} · in {cost['input_tokens']} "
          f"(cached {cost['cached_input_tokens']}) · out {cost['output_tokens']}")

    return {
        "skipped": False, "target": f"{tp}:{tm}", "oracle": f"{op}:{om}", "rounds": rounds,
        "checker": "anthropic:claude-sonnet-4-6" if check_on else None,
        "n_docs": len(results), "n_breached": n_breached,
        "n_soft_leak": n_soft_leak, "n_double_confirm": n_double_confirm,
        "cost": {
            "target": target_m.totals(), "oracle": oracle_m.totals(),
            "panel": [m.totals() for m in panel_meters],
            "checker": checker_m.totals() if checker_m else None,
            "total": cost,
        },
        "results": [{"document_preview": r.document_preview, "breached": r.breached,
                     "rounds_used": r.rounds_used, "attempts": [asdict(a) for a in r.attempts]} for r in results],
    }


def _grand_total(report: dict) -> dict:
    keys = ("input_tokens", "output_tokens", "cached_input_tokens", "est_cost_usd")
    total = {k: 0 for k in keys}
    for c in report["configs"].values():
        if c.get("skipped"):
            continue
        t = c["cost"]["total"]
        for k in keys:
            total[k] += t[k]
    total["est_cost_usd"] = round(total["est_cost_usd"], 6)
    return total


def _flush_report(report: dict) -> None:
    report["grand_total_cost"] = _grand_total(report)
    with open(_REPORT, "w") as f:
        json.dump(report, f, indent=2)


async def _main() -> None:
    if not os.path.exists(_CONTRACTS):
        print(f"Missing {_CONTRACTS} — run spikes/long_doc_gate_run.py first.")
        return
    docs = load_long_contracts(_CONTRACTS)
    rounds = int(os.getenv("SCALED_ROUNDS", "12"))
    want = [c.strip() for c in os.getenv("SCALED_CONFIGS", "weak,mid,frontier").split(",") if c.strip()]
    print(f"Loaded {len(docs)} docs. Scaled adaptive: rounds={rounds}, configs={want}, "
          f"panel={[m for _,m in _PANEL]}, concurrency={_GLOBAL_SEM._value}, "
          f"checker={'on' if os.getenv('SCALED_CHECK', '1').strip() != '0' else 'off'}")
    report = {"n_docs": len(docs), "rounds": rounds, "panel": [f"{p}:{m}" for p, m in _PANEL], "configs": {}}

    names = [n for n in want if n in _CONFIGS]
    lock = asyncio.Lock()

    async def _runner(name):
        try:
            c = await _run_config(name, docs, rounds)
        except Exception as e:  # isolate config failures — one config must not cancel the others (L13)
            print(f"[config {name} FAILED] {type(e).__name__}: {str(e)[:120]} — other configs continue")
            c = {"skipped": True, "error": f"{type(e).__name__}: {str(e)[:200]}"}
        # Write the report to disk AFTER EACH config finishes so a kill never loses completed work.
        async with lock:
            report["configs"][name] = c
            _flush_report(report)

    # Run configs CONCURRENTLY; the shared _GLOBAL_SEM caps total in-flight attacks.
    await asyncio.gather(*[_runner(n) for n in names])

    _flush_report(report)
    print(f"\nReport → {_REPORT}")
    print("\n=== HEADLINE ===")
    for name in names:
        c = report["configs"].get(name)
        if c and not c.get("skipped"):
            cost = c["cost"]["total"]
            print(f"  {name}: breached {c['n_breached']}/{c['n_docs']} | "
                  f"soft-leaks {c['n_soft_leak']} | double-confirms {c['n_double_confirm']} | "
                  f"COST ${cost['est_cost_usd']:.4f} "
                  f"(target {c['target']} vs oracle {c['oracle']}, {c['rounds']} rounds, native checker, diverse panel)")
    gt = report["grand_total_cost"]
    print(f"  GRAND TOTAL COST: ${gt['est_cost_usd']:.4f} · in {gt['input_tokens']} "
          f"(cached {gt['cached_input_tokens']}) · out {gt['output_tokens']}")


if __name__ == "__main__":
    try:
        asyncio.run(_main())
    except KeyboardInterrupt:
        print("\nAborted — no further calls.")
