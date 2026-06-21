"""Mitigation probe -- earns (or retires) the word "irreducibly" before it reaches the abstract.

The stability probe showed the composite-class seam is unstable both across phrasings and across
repeated runs of the IDENTICAL string. Before claiming that instability is "irreducible / not to
be engineered away" (the load-bearing verb in the abstract + the justification for routing the
class out of auto-settle), we must try the two obvious engineering moves a reviewer will name:

  (M1) TEMPERATURE-0.  The verifier ALREADY calls complete(temperature=0.0). For the frontier
       judges this changes nothing -- gpt-5 / gpt-5.1 are reasoning-family, so the backend omits
       temperature (the API rejects non-default), and they sample regardless. So temp-0 is NOT an
       available knob on the judges you'd deploy as "frontier"; the run-level flips happen despite
       a temp-0 request. We make that visible by contrasting a NON-reasoning strong judge
       (gpt-4.1) at temp 0 (honored -> should be run-deterministic) vs temp 1.0 (sampling) -- this
       proves temperature IS the run-noise lever when available, and that it is unavailable for
       the reasoning judges. The residual question for gpt-4.1@temp-0: does determinism settle the
       seam, or does it stay PHRASING-sensitive (same fact, two wordings, opposite firm verdict)?

  (M2) SELF-CONSISTENCY / MAJORITY VOTE.  k=5 samples per (judge, claim); read the vote split.
       If splits are degenerate (0/5 or 5/5) a majority gives a stable answer -> voting rescues.
       If splits are fragile (2/5 or 3/5) the 5-vote majority is itself a near-coin-flip -> voting
       does NOT rescue (the per-sample p sits near 0.5). Note a firm 5/0 within each phrasing that
       DISAGREES across phrasings is the worst case: voting per-prompt entrenches the wrong verdict
       on one wording rather than fixing it.

Fired at the 4 worst-flipping composite items (C1, C3, C5, C7), both phrasings = 8 claims.

PRE-REGISTERED READING RULE (committed before any result is read):
  "IRREDUCIBLE at the frontier judges" is EARNED iff BOTH:
    (a) gpt-5 AND gpt-5.1 show fragile majority splits (>= ~1/3 of the 8 claims land at 2/5 or
        3/5, i.e. the 5-vote majority is not robust), AND
    (b) gpt-4.1@temp-0 is run-deterministic yet still FLIPS its verdict across the two phrasings
        of at least one item (phrasing-noise survives determinism).
  It is RETIRED to "reducible by sampling/determinism discipline" if EITHER:
    (a') majority vote concentrates the reasoning judges (splits mostly degenerate -> a vote
         settles them), OR
    (b') gpt-4.1@temp-0 returns one consistent verdict per item across BOTH phrasings (a
         deterministic non-reasoning judge settles the seam).
  Whichever the data shows decides the abstract verb. The rule is not re-chosen after results.

  cd agent-exchange && .venv/bin/python spikes/mitigation_probe.py
  DRY_RUN=1 ...                 # plan only
  K=5 ...                       # votes per claim
Output: data/eval/mitigation_probe_report.json   (checkpointed after every config)
"""

from __future__ import annotations

import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from dotenv import load_dotenv

from agent_exchange.core import make_backend
from agent_exchange.core.types import CompletionResult, Message  # noqa: F401
from agent_exchange.core.backend import ModelBackend
from agent_exchange.eval.long_corpus import load_long_contracts
from agent_exchange.verify import Verifier
from agent_exchange.verify.schema import DEFAULT_THRESHOLD, Verdict

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(_ROOT, ".env"))
_CONTRACTS = os.path.join(_ROOT, "data", "eval", "long_contracts.json")
_REPORT = os.path.join(_ROOT, "data", "eval", "mitigation_probe_report.json")

# The 4 worst-flipping composite items from the stability probe, both phrasings (doc 2=SaaS, 1=MSA).
ITEMS = [
    {"id": "C1_credit_3mo_60", "doc": 2, "variants": [
        "Over three consecutive calendar months in each of which the Service misses the uptime SLA, the "
        "maximum cumulative service credit the Customer can receive is 60% of the monthly Fees.",
        "If the Service breaches the uptime SLA every month for a full quarter, the Customer's service credits "
        "can total as much as 60% of a single month's Fees across that quarter."]},
    {"id": "C3_credit_2plus1_50", "doc": 2, "variants": [
        "If the SLA is missed by the maximum margin in two months and by a 2% margin in a third, the Customer's "
        "total service credit across the three months is 50% of the monthly Fees.",
        "Across a quarter with two full-cap breaches and one month 2% below the uptime threshold, cumulative "
        "service credits reach 50% of one month's Fees."]},
    {"id": "C5_interest_12mo_18", "doc": 2, "variants": [
        "Over a full year of nonpayment, late-payment interest reaches 18% of the invoiced amount.",
        "An invoice unpaid for twelve months accrues total late interest equal to 18% of the Fees."]},
    {"id": "C7_msa_250k_flat", "doc": 1, "variants": [
        "Under the MSA, no claim against the Service Provider arising from a single Statement of Work can "
        "recover more than $250,000.",
        "The Service Provider's maximum liability per Statement of Work is capped at $250,000."]},
]

# (label, provider, model, temperature, honored?) -- temperature only honored for non-reasoning models.
CONFIGS = [
    ("gpt5_default", "openrouter", "openai/gpt-5", None, False),       # reasoning: temp omitted, samples
    ("gpt5.1_default", "openrouter", "openai/gpt-5.1", None, False),   # reasoning: temp omitted, samples
    ("gpt4.1_temp0", "openrouter", "openai/gpt-4.1", 0.0, True),       # non-reasoning: temp-0 honored
    ("gpt4.1_temp1", "openrouter", "openai/gpt-4.1", 1.0, True),       # non-reasoning: temp-1 sampling
]


class _TempForce(ModelBackend):
    """Wrap a backend so the temperature the Verifier hardcodes (0.0) is overridden with ours.
    For reasoning models the inner adapter drops temperature anyway -- this only bites non-reasoning."""

    def __init__(self, inner, temp):
        self._inner = inner
        self._temp = temp
        self.provider = inner.provider
        self.model = inner.model

    async def complete(self, messages, *, temperature=0.0, max_tokens=None):
        return await self._inner.complete(messages, temperature=self._temp, max_tokens=max_tokens)


def _save(r):
    json.dump(r, open(_REPORT, "w"), indent=2)


async def _one(sem, verifier, doc, claim):
    async with sem:
        try:
            vd = (await verifier.verify(doc, [claim]))[0]
            paid = bool(vd.verdict is Verdict.CONFIRMED and vd.confidence >= DEFAULT_THRESHOLD
                        and not vd.needs_human(DEFAULT_THRESHOLD))
            return paid, round(vd.confidence, 2)
        except Exception as e:  # noqa: BLE001
            return None, f"ERR:{str(e)[:30]}"


async def _main():
    sys.stdout.reconfigure(line_buffering=True)
    if not (os.getenv("OPENROUTER_API_KEY") or "").strip():
        print("Need OPENROUTER_API_KEY. Exiting."); return
    k = int(os.getenv("K", "5"))
    n_claims = sum(len(it["variants"]) for it in ITEMS)
    planned = n_claims * k * len(CONFIGS)
    print(f"=== mitigation probe: {len(ITEMS)} items x 2 phrasings = {n_claims} claims, k={k} votes, "
          f"{len(CONFIGS)} configs => {planned} calls ===")
    for lbl, _, model, temp, honored in CONFIGS:
        print(f"   {lbl:16s} {model:18s} temp={temp} honored={honored}")
    if (os.getenv("DRY_RUN") or "").strip() == "1":
        print("DRY_RUN=1 -> plan only."); return

    docs = load_long_contracts(_CONTRACTS)
    sem = asyncio.Semaphore(int(os.getenv("CONCURRENCY", "6")))
    report = {"design": {"k": k, "items": [it["id"] for it in ITEMS],
                         "configs": [{"label": c[0], "model": c[2], "temp": c[3], "temp_honored": c[4]}
                                     for c in CONFIGS]},
              "reading_rule": "IRREDUCIBLE earned iff (a) gpt-5 & gpt-5.1 fragile majority splits (>=~1/3 of "
                              "claims at 2/5-3/5) AND (b) gpt-4.1@temp0 run-deterministic yet flips across "
                              "phrasings of some item. RETIRED to 'reducible' if voting concentrates the "
                              "reasoning judges OR gpt-4.1@temp0 gives one verdict per item across phrasings. "
                              "Pre-registered; not re-chosen after results.",
              "results": {}}
    for (lbl, prov, model, temp, honored) in CONFIGS:
        inner = make_backend(prov, model)
        backend = _TempForce(inner, temp) if temp is not None else inner
        v = Verifier(backend)
        print(f"\n=== {lbl} ({model}, temp={temp}, honored={honored}) ===")
        items_out = {}
        for it in ITEMS:
            doc = docs[it["doc"]]
            vouts = []
            for vi, claim in enumerate(it["variants"]):
                res = await asyncio.gather(*[_one(sem, v, doc, claim) for _ in range(k)])
                pays = [r[0] for r in res if r[0] is True]
                valid = [r for r in res if r[0] is not None]
                n_pay = len(pays)
                n_val = len(valid)
                majority = "PAY" if n_pay * 2 > n_val else "REJECT" if n_val else "NA"
                fragile = n_val >= 3 and (n_val * 0.34 <= n_pay <= n_val * 0.66)  # ~2/5..3/5 band
                vouts.append({"phrasing": vi, "n_pay": n_pay, "n_valid": n_val, "majority": majority,
                              "fragile": fragile, "confidences": [r[1] for r in res], "claim": claim})
                print(f"    {it['id']:22s} p{vi}: {n_pay}/{n_val} -> {majority:6s} "
                      f"{'[FRAGILE]' if fragile else ''}")
            cross = "AGREE" if len({vo["majority"] for vo in vouts}) == 1 else "DISAGREE"
            items_out[it["id"]] = {"variants": vouts, "cross_phrasing": cross}
            print(f"    {it['id']:22s} cross-phrasing majority: {cross}")
        report["results"][lbl] = {"model": model, "temp": temp, "temp_honored": honored, "items": items_out}
        _save(report)

    # ---- summary against the rule ----
    print(f"\nReport -> {_REPORT}")
    print("\n=== M2 majority-vote: fragile splits + cross-phrasing disagreement per config ===")
    for lbl, res in report["results"].items():
        frg = sum(1 for it in res["items"].values() for vo in it["variants"] if vo["fragile"])
        tot = sum(len(it["variants"]) for it in res["items"].values())
        dis = sum(1 for it in res["items"].values() if it["cross_phrasing"] == "DISAGREE")
        print(f"  {lbl:16s}: fragile {frg}/{tot} phrasings   cross-phrasing DISAGREE {dis}/{len(res['items'])} items")
    print("\n=== M1 temp-0 determinism (gpt-4.1@temp0 should be ~firm; gpt-5/5.1 sample regardless) ===")
    for lbl in ("gpt4.1_temp0", "gpt4.1_temp1", "gpt5_default", "gpt5.1_default"):
        if lbl not in report["results"]:
            continue
        res = report["results"][lbl]
        firm = sum(1 for it in res["items"].values() for vo in it["variants"]
                   if vo["n_valid"] and vo["n_pay"] in (0, vo["n_valid"]))
        tot = sum(len(it["variants"]) for it in res["items"].values())
        print(f"  {lbl:16s}: run-firm (0/k or k/k) {firm}/{tot} phrasings")


if __name__ == "__main__":
    try:
        asyncio.run(_main())
    except KeyboardInterrupt:
        print("\nAborted - no further calls.")
