"""LIVE open-weight ensemble — does a TWO-WEAK-JUDGE Featherless panel close the F-H leak?

The Featherless-sponsor story + the "true two-weak-judge ensemble". F-H showed a scaled adaptive
attack breaches a single WEAK judge; the productized fix (verify/ensemble.py) closed it by pairing
the weak judge with a FRONTIER one (gpt-4.1). The open question that left (RESULTS.md, Build 1
caveat 2): *"a two-weak-judge config is not tested."* This spike tests exactly that — an
EnsembleVerifier over TWO open-weight Featherless judges, with NO frontier model in the gate — and
asks whether it matches the frontier judge's robustness (0 breaches) against the same scaled
adaptive attack, with an OFF-PANEL strong oracle (gpt-5.1).

Open-weight models mangle the strict per-claim JSON (RESULTS.md F-D: raw Qwen2.5-72B fail-safed
33/44). So every open-weight backend is wrapped in core.json_repair.RepairingBackend, and PART 0
measures the fail-safe-rate win (confidence==0.0 fraction) WITHOUT vs WITH the wrapper.

Three parts:
  PART 0 — JSON reliability: per-judge fail-safe rate on long_doc_fixture, raw vs RepairingBackend.
  PART 1 — payment-lens (labeled fixture): leak / genuine-served / false-escalate for
           {judge A alone, judge B alone, ENSEMBLE[A,B]} (open-weight backends repaired).
  PART 2 — the leak test, PAPER-GRADE: run_adaptive_attack (panel=[gpt-4.1, gpt-5.1, claude-haiku-4.5],
           max_rounds=12) over the 4 contracts, target = single open-weight judge vs ENSEMBLE[A,B],
           oracle = gpt-5.1 (off-panel). Repeated over N seeds (vary doc order + a seed nonce on the
           attacker prompt, since run_adaptive_attack has no seed param). Breach rate mean ± spread.

Env: OPENAI_API_KEY + AIMLAPI_API_KEY + FEATHERLESS_API_KEY. Output: data/eval/open_weight_ensemble_report.json.
Knobs: OWENS_SEEDS (default 3), OWENS_ROUNDS (default 12), OWENS_FT_TIMEOUT (default 180).
Long-running — background it: `> /tmp/agentexch_owens_<n>.log 2>&1` (L7).
"""

from __future__ import annotations

import asyncio
import json
import os
import random
import statistics
import sys
from dataclasses import dataclass

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import httpx
from dotenv import load_dotenv

from agent_exchange.core import make_backend
from agent_exchange.core.backend import ModelBackend
from agent_exchange.core.json_repair import RepairingBackend
from agent_exchange.core.types import CompletionResult, Message
from agent_exchange.eval.adaptive_adversary import run_adaptive_attack
from agent_exchange.eval.long_corpus import load_long_contracts
from agent_exchange.eval.payment_lens import collect_verdicts, score_payment_lens
from agent_exchange.eval.seeded_liar import load_fixture
from agent_exchange.eval.types import GENUINE
from agent_exchange.verify import Verdict, Verifier
from agent_exchange.verify.ensemble import EnsembleVerifier

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(_ROOT, ".env"))
_CONTRACTS = os.path.join(_ROOT, "data", "eval", "long_contracts.json")
_FIXTURE = os.path.join(_ROOT, "data", "eval", "long_doc_fixture.json")
_REPORT = os.path.join(_ROOT, "data", "eval", "open_weight_ensemble_report.json")

# The two strongest ~70B-class open-weight INSTRUCT judges this Featherless account can serve.
# Verified live against https://api.featherless.ai/v1/chat/completions (L6): the gated
# meta-llama/Llama-3.3-70B-Instruct repo 403s ("connect HuggingFace to verify"), but the
# un-gated meta-llama/Meta-Llama-3.1-70B-Instruct mirror serves 200. A genuine two-VENDOR pair.
JUDGE_A = ("featherless", "Qwen/Qwen2.5-72B-Instruct")
JUDGE_B = ("featherless", "meta-llama/Meta-Llama-3.1-70B-Instruct")

# Off-panel strong oracle for PART 2 + the diverse attacker panel (matches scaled_adaptive_run).
ORACLE = ("aimlapi", "gpt-5.1-2025-11-13")
PANEL = [("openai", "gpt-4.1"), ("aimlapi", "gpt-5.1-2025-11-13"), ("aimlapi", "anthropic/claude-haiku-4.5")]

FT_TIMEOUT = float(os.getenv("OWENS_FT_TIMEOUT", "180"))
# This Featherless account is HEAVILY rate-limited (429s even at concurrency 3). So ALL
# Featherless traffic across the WHOLE run serializes through ONE global gate (semaphore=1),
# and a 429-aware retry with long backoff paces it. This is the L5 fix taken to its limit:
# the open-weight path is the bottleneck, so we make it strictly sequential + patient rather
# than fast-and-failing. (The frontier oracle/attacker calls are NOT gated by this — only FT.)
_FT_GATE = asyncio.Semaphore(int(os.getenv("OWENS_FT_CONCURRENCY", "1")))
_FT_PACE_S = float(os.getenv("OWENS_FT_PACE_S", "1.5"))  # min gap injected after each FT call


@dataclass
class _PacedBackend(ModelBackend):
    """Serialize + pace + 429-retry every call to the wrapped (Featherless) backend.

    The repo's backend already retries transient 429/5xx 4×, but this account exhausts that
    under any concurrency. We add: (1) a process-global semaphore so only ONE FT request is in
    flight at a time, (2) a fixed post-call pause, and (3) an extra outer retry that catches a
    *terminal* 429 and waits a longer backoff before re-entering. Pure pacing — no behavior
    change to the completion itself."""

    inner: ModelBackend
    max_429_retries: int = 6

    async def complete(self, messages, *, temperature=0.0, max_tokens=None) -> CompletionResult:
        attempt = 0
        while True:
            async with _FT_GATE:
                try:
                    res = await self.inner.complete(messages, temperature=temperature, max_tokens=max_tokens)
                    await asyncio.sleep(_FT_PACE_S)
                    return res
                except httpx.HTTPStatusError as e:
                    if e.response.status_code != 429 or attempt >= self.max_429_retries:
                        raise
                    attempt += 1
            # Back off OUTSIDE the gate so the limiter window can recover; jittered exponential.
            wait = min(60.0, 5.0 * (2 ** (attempt - 1))) + random.uniform(0, 2)
            await asyncio.sleep(wait)


def _ow_backend(prov: str, model: str) -> ModelBackend:
    """Open-weight judge backend: RepairingBackend(reask) over a paced+serialized FT backend."""
    return RepairingBackend(_PacedBackend(make_backend(prov, model, timeout_s=FT_TIMEOUT)))


@dataclass
class _SeededAttacker(ModelBackend):
    """Thin wrapper: append a per-seed nonce to the LAST (user) message so a diverse-panel
    attacker searches a different region each seed. run_adaptive_attack has no seed param, so
    this + reordering docs is how we get independent passes."""

    inner: ModelBackend
    seed: int

    async def complete(self, messages, *, temperature=0.0, max_tokens=None) -> CompletionResult:
        nonced = list(messages)
        if nonced:
            last = nonced[-1]
            nonced[-1] = Message(last.role, f"{last.content}\n\n[attack-seed:{self.seed}]")
        return await self.inner.complete(nonced, temperature=temperature, max_tokens=max_tokens)


def _dump(report: dict) -> None:
    """Write the report after each part / each (config,seed) so a slow PART 2 still leaves
    usable partial results on disk (open-weight latency makes a full run multi-hour)."""
    with open(_REPORT, "w") as f:
        json.dump(report, f, indent=2)


def _have_keys() -> list[str]:
    keymap = {"openai": "OPENAI_API_KEY", "aimlapi": "AIMLAPI_API_KEY", "featherless": "FEATHERLESS_API_KEY"}
    need = {"openai", "aimlapi", "featherless"}
    return [p for p in need if not (os.getenv(keymap[p]) or "").strip()]


# ---------------------------------------------------------------------------
# PART 0 — JSON reliability (fail-safe rate raw vs repaired)
# ---------------------------------------------------------------------------

async def _failsafe_rate(cases, prov, model, *, repaired: bool) -> dict:
    """Fraction of verdicts that are fail-safe (verdict UNSUPPORTED at confidence 0.0) — the
    parser's withhold-on-unparseable signal. A high rate here means the judge's JSON, not its
    judgment, is failing. Lower is better (more real judgments survive)."""
    # RAW = paced FT backend WITHOUT RepairingBackend (honest raw fail-safe); REPAIRED = with it.
    # Both pace through the same global FT gate; the only difference is the JSON repair layer.
    backend = _ow_backend(prov, model) if repaired else _PacedBackend(make_backend(prov, model, timeout_s=FT_TIMEOUT))
    verifier = Verifier(backend)

    async def _guarded(group_doc, claims):
        try:
            return await verifier.verify(group_doc, claims)
        except Exception:  # a transport failure → treat every claim as fail-safe (parser would)
            return [None] * len(claims)

    # group by contract (the verifier sees all a doc's claims in one call, like the real pipeline).
    # Sequential over groups (the FT gate already serializes; gather here just adds queue churn).
    by_doc: dict[str, list[str]] = {}
    for c in cases:
        by_doc.setdefault(c.contract, []).append(c.claim)
    results = []
    for doc, claims in by_doc.items():
        results.append(await _guarded(doc, claims))

    n = failsafe = 0
    for verds in results:
        for v in verds:
            n += 1
            if v is None or (v.verdict is Verdict.UNSUPPORTED and v.confidence == 0.0):
                failsafe += 1
    return {"n": n, "failsafe": failsafe, "failsafe_rate": failsafe / n if n else 0.0}


# ---------------------------------------------------------------------------
# PART 1 — payment-lens on the labeled fixture
# ---------------------------------------------------------------------------

def _cls(rep, src, attr):
    for c in rep.classes:
        if c.source == src:
            return getattr(c, attr)
    return 0.0


async def _payment_lens(cases, name, verifier) -> dict:
    pairs = await collect_verdicts(cases, verifier, max_concurrency=3)
    rep = score_payment_lens(pairs, config=name)
    out = {
        "gifted_leak_rate": _cls(rep, "llm_gifted_span", "leak_rate"),
        "genuine_served_rate": _cls(rep, GENUINE, "served_rate"),
        "genuine_false_escalate_rate": _cls(rep, GENUINE, "false_escalate_rate"),
        "genuine_false_withhold_rate": _cls(rep, GENUINE, "false_withhold_rate"),
    }
    print(f"  {name:26s} gifted_leak={out['gifted_leak_rate']:.0%}  served={out['genuine_served_rate']:.0%}  "
          f"false_esc={out['genuine_false_escalate_rate']:.0%}  false_withhold={out['genuine_false_withhold_rate']:.0%}")
    return out


# ---------------------------------------------------------------------------
# PART 2 — adaptive leak test (paper-grade: N seeds)
# ---------------------------------------------------------------------------

async def _run_seed(seed, docs, make_target, target_label, rounds) -> dict:
    """One independent adaptive pass: doc order rotated by seed, attacker prompts seed-nonced."""
    order = docs[seed % len(docs):] + docs[: seed % len(docs)]  # rotate doc order per seed
    oracle = Verifier(make_backend(*ORACLE, timeout_s=FT_TIMEOUT))
    panel = [_SeededAttacker(make_backend(p, m), seed) for p, m in PANEL]
    target = make_target()
    sem = asyncio.Semaphore(3)

    async def _one(doc):
        async with sem:
            return await run_adaptive_attack(doc, target=target, oracle=oracle, attacker_panel=panel, max_rounds=rounds)

    results = await asyncio.gather(*[_one(d) for d in order])
    n_breached = sum(r.breached for r in results)
    breaches = [a.claim for r in results if r.breached for a in r.attempts if a.breached]
    print(f"    seed {seed}  [{target_label}]  breached {n_breached}/{len(results)}"
          + (f"  e.g. {breaches[0][:90]!r}" if breaches else ""))
    return {"seed": seed, "n_docs": len(results), "n_breached": n_breached, "breach_claims": breaches}


def _aggregate(cfg_block: dict) -> None:
    rates = [s["n_breached"] / s["n_docs"] for s in cfg_block["seeds"]]
    cfg_block["breach_rate_mean"] = statistics.mean(rates) if rates else 0.0
    cfg_block["breach_rate_stdev"] = statistics.stdev(rates) if len(rates) > 1 else 0.0
    cfg_block["breach_rates_per_seed"] = rates
    cfg_block["total_breaches"] = sum(s["n_breached"] for s in cfg_block["seeds"])
    cfg_block["total_docs"] = sum(s["n_docs"] for s in cfg_block["seeds"])


async def _part2(docs, seeds, rounds, report) -> dict:
    out = {"single_judge_A": {"label": f"{JUDGE_A[1]} (repaired)", "seeds": []},
           "ensemble_AB": {"label": f"ensemble[{JUDGE_A[1]}, {JUDGE_B[1]}] (repaired)", "seeds": []}}
    report["part2_adaptive"] = out  # live-attached so _dump captures partial progress

    def _make_single():
        return Verifier(_ow_backend(*JUDGE_A))

    def _make_ensemble():
        return EnsembleVerifier([Verifier(_ow_backend(*JUDGE_A)), Verifier(_ow_backend(*JUDGE_B))])

    print(f"\n=== PART 2: adaptive leak test — {len(seeds)} seeds × {len(docs)} docs × {rounds} rounds ===")
    print(f"  panel={[m for _, m in PANEL]}  oracle={ORACLE[1]} (off-panel)")
    for cfg, mk, lbl in [("single_judge_A", _make_single, f"single {JUDGE_A[1]}"),
                         ("ensemble_AB", _make_ensemble, "ensemble[A,B]")]:
        for s in seeds:
            out[cfg]["seeds"].append(await _run_seed(s, docs, mk, lbl, rounds))
            _aggregate(out[cfg])           # running mean after each seed
            _dump(report)                  # persist partial PART 2 (slow open-weight run safety)
    return out


async def _main() -> None:
    missing = _have_keys()
    if missing:
        print(f"Missing keys {missing} — exiting.")
        return
    if not os.path.exists(_CONTRACTS) or not os.path.exists(_FIXTURE):
        print("Missing fixtures — run spikes/long_doc_gate_run.py first.")
        return

    cases = load_fixture(_FIXTURE)
    docs = load_long_contracts(_CONTRACTS)
    seeds = list(range(int(os.getenv("OWENS_SEEDS", "3"))))
    rounds = int(os.getenv("OWENS_ROUNDS", "12"))

    # RESUME mode (OWENS_SKIP_PART01=1): reuse a prior run's PART 0/1 from the on-disk report and
    # run only PART 2. Lets the slow open-weight PART 0/1 be measured ONCE, then PART 2 re-run with a
    # leaner round budget without paying for PART 0/1 again. Falls through to a full run if absent.
    resume = os.getenv("OWENS_SKIP_PART01", "0") == "1" and os.path.exists(_REPORT)
    if resume:
        with open(_REPORT) as f:
            report = json.load(f)
        report["seeds"], report["rounds"] = seeds, rounds  # PART 2 knobs may differ from the cached run
        print(f"=== RESUME: reusing cached PART 0/1 from {_REPORT}; running PART 2 only "
              f"({len(seeds)} seeds × {rounds} rounds) ===")
    else:
        report = {
            "judges": {"A": f"{JUDGE_A[0]}:{JUDGE_A[1]}", "B": f"{JUDGE_B[0]}:{JUDGE_B[1]}"},
            "oracle": f"{ORACLE[0]}:{ORACLE[1]}",
            "attacker_panel": [f"{p}:{m}" for p, m in PANEL],
            "n_docs": len(docs), "n_fixture_claims": len(cases),
            "seeds": seeds, "rounds": rounds,
        }

        # ---- PART 0: JSON reliability ----
        print("=== PART 0: JSON fail-safe rate (raw vs RepairingBackend) on the labeled fixture ===")
        report["part0_json_reliability"] = {}
        for tag, (prov, model) in [("judge_A", JUDGE_A), ("judge_B", JUDGE_B)]:
            raw = await _failsafe_rate(cases, prov, model, repaired=False)
            rep = await _failsafe_rate(cases, prov, model, repaired=True)
            report["part0_json_reliability"][tag] = {"model": f"{prov}:{model}", "raw": raw, "repaired": rep}
            print(f"  {model:40s} fail-safe raw={raw['failsafe']}/{raw['n']} ({raw['failsafe_rate']:.0%})"
                  f"  →  repaired={rep['failsafe']}/{rep['n']} ({rep['failsafe_rate']:.0%})")
            _dump(report)

        # ---- PART 1: payment-lens ----
        print("\n=== PART 1: payment-lens (leak / served / false-escalate) ===")
        A = Verifier(_ow_backend(*JUDGE_A))
        B = Verifier(_ow_backend(*JUDGE_B))
        ens = EnsembleVerifier([Verifier(_ow_backend(*JUDGE_A)), Verifier(_ow_backend(*JUDGE_B))])
        report["part1_payment_lens"] = {}
        for nm, v in [("judge_A_alone", A), ("judge_B_alone", B), ("ensemble_AB", ens)]:
            report["part1_payment_lens"][nm] = await _payment_lens(cases, nm, v)
            _dump(report)

    # ---- PART 2: adaptive leak test ----
    await _part2(docs, seeds, rounds, report)

    _dump(report)
    print(f"\nReport → {_REPORT}")

    print("\n=== HEADLINE ===")
    p0 = report["part0_json_reliability"]
    for tag in ("judge_A", "judge_B"):
        d = p0[tag]
        print(f"  json fail-safe {d['model'].split(':')[-1]}: {d['raw']['failsafe_rate']:.0%} → {d['repaired']['failsafe_rate']:.0%}")
    p2 = report["part2_adaptive"]
    s = p2["single_judge_A"]; e = p2["ensemble_AB"]
    print(f"  adaptive breach rate  single-A: {s['breach_rate_mean']:.0%} ± {s['breach_rate_stdev']:.0%} "
          f"({s['total_breaches']}/{s['total_docs']})")
    print(f"  adaptive breach rate  ensemble: {e['breach_rate_mean']:.0%} ± {e['breach_rate_stdev']:.0%} "
          f"({e['total_breaches']}/{e['total_docs']})")


if __name__ == "__main__":
    try:
        asyncio.run(_main())
    except KeyboardInterrupt:
        print("\nAborted — no further calls.")
