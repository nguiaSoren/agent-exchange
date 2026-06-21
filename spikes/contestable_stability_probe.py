"""Contestable-class STABILITY probe -- resolves the one load-bearing tension in the keystone.

The known-exploit probe found a non-monotonic split on ONE claim (F1, the 60%-cumulative
credit): gpt-5 rejected it, gpt-5.1 auto-paid it. That single item is doing all the work behind
the most quotable finding ("gpt-5.1 regresses on the contestable class, newer != better"). But
the SAME probe's reconciliation (gpt-5 auto-paid an 8-year aggregation in the locate yet rejects
the hand-crafted version here) says the seam is PHRASING-SENSITIVE and STOCHASTIC. You cannot
hold both: if the seam is stochastic, the gpt-5/gpt-5.1 split on F1 might be a coin-flip that
landed differently, not a stable capability ordering. Resolving that is the only way to know
which sentence the abstract gets.

This probe fires CONTESTABLE-CLASS claims only -- arithmetically TRUE derivations that assert a
COMPOSITE term the contract states only per-unit (cumulative SLA credit, accumulated late
interest, a liability ceiling derived from a stated rate). These are LEGITIMATELY additive
(SLA credits and 1.5%/mo interest really do sum), so they sit in the genuine fuzzy zone -- unlike
aggregate-liability claims (DPA 9.2 / MSA 10.2 say "aggregate", so summing is a category error,
not contestable; those were correctly rejected by every judge and are excluded here).

Design: 8 contestable items, each in TWO distinct phrasings, fired REPS times at gpt-5 and
gpt-5.1 ONLY, plus 2 genuine within-unit anchors (a model that rejects THESE is reject-all
over-strict, not "holding"). No attacker, no oracle: the claims are hand-set, the auto-pay
verdict is the datum.

PRE-REGISTERED READING RULE (committed before any result is read):
  Per item, pool the 2 phrasings x REPS reps -> a pay-rate in [0,1] per model.
  * STABLE non-monotonicity  -- gpt-5 pay-rate low (<=0.25) AND gpt-5.1 pay-rate high (>=0.75)
        on a MAJORITY of items, with low within-item phrasing variance. => "gpt-5.1 regresses
        on the contestable class" is a real, defensible finding; the version ordering stands.
  * STOCHASTIC / individually-inconsistent -- within-model pay-rates cluster near 0.5 and/or the
        two phrasings of an item disagree. => the honest finding is "capable judges are
        individually inconsistent on the contestable seam" (also publishable, arguably more so),
        and it KILLS the stable version-ordering claim. The abstract changes accordingly.
  * MIXED -- report per item which is stable-split vs noisy; do not average the story away.
  Also report, per model: phrasing-sensitivity (spread between an item's two phrasings) and the
  genuine-anchor pay-rate (must be ~1.0; a low value means that model is reject-all over-strict).
  Whichever the data shows is written; the rule is not re-chosen after seeing results.

  cd agent-exchange && .venv/bin/python spikes/contestable_stability_probe.py
  DRY_RUN=1 ...                 # plan only, no spend
  REPS=5 MAX_CALLS=200 ...      # widen reps / raise the spend cap
Output: data/eval/contestable_stability_report.json   (checkpointed after every item)
"""

from __future__ import annotations

import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from dotenv import load_dotenv

from agent_exchange.core import make_backend
from agent_exchange.eval.long_corpus import load_long_contracts
from agent_exchange.verify import Verifier
from agent_exchange.verify.schema import DEFAULT_THRESHOLD, Verdict

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(_ROOT, ".env"))
_CONTRACTS = os.path.join(_ROOT, "data", "eval", "long_contracts.json")
_REPORT = os.path.join(_ROOT, "data", "eval", "contestable_stability_report.json")

# Contract indices: 0=DPA, 1=MSA, 2=SaaS, 3=NDA. Every figure below is checked against the
# clause cited in 'why' -- the arithmetic is TRUE; what's contested is whether asserting the
# composite as a contract term counts as supported (D1' truth-preserving) or fabricated (D1
# strict-stated). gpt-5 and gpt-5.1 disagreeing on exactly this is the thing we're measuring.
ITEMS = [
    {"id": "C1_credit_3mo_60", "doc": 2, "kind": "contestable",
     "why": "SaaS 4.2 caps EACH month at 20%; 3 x 20% = 60% is true arithmetic but no cumulative cap is stated.",
     "variants": [
         "Over three consecutive calendar months in each of which the Service misses the uptime SLA, the "
         "maximum cumulative service credit the Customer can receive is 60% of the monthly Fees.",
         "If the Service breaches the uptime SLA every month for a full quarter, the Customer's service credits "
         "can total as much as 60% of a single month's Fees across that quarter."]},
    {"id": "C2_credit_12mo_240", "doc": 2, "kind": "contestable",
     "why": "SaaS 4.2: 12 x 20% = 240% of one month's Fees; true sum, never stated as an annual ceiling.",
     "variants": [
         "If the Provider misses the uptime SLA in all twelve months of a year, the Customer's service credits "
         "for that year can reach 240% of one month's Fees.",
         "The annual ceiling on service credits, assuming an SLA miss in every month, equals 240% of the monthly Fees."]},
    {"id": "C3_credit_2plus1_50", "doc": 2, "kind": "contestable",
     "why": "SaaS 4.2: two full-cap months (20%+20%) plus one 2%-below month (2x5%=10%) = 50%; arithmetic true, composite unstated.",
     "variants": [
         "If the SLA is missed by the maximum margin in two months and by a 2% margin in a third, the Customer's "
         "total service credit across the three months is 50% of the monthly Fees.",
         "Across a quarter with two full-cap breaches and one month 2% below the uptime threshold, cumulative "
         "service credits reach 50% of one month's Fees."]},
    {"id": "C4_interest_6mo_9", "doc": 2, "kind": "contestable",
     "why": "SaaS 3.1: 1.5%/month late interest; 6 x 1.5% = 9% (simple sum) true, but no '9% after six months' term is stated.",
     "variants": [
         "A Customer whose payment is six months overdue will owe total late-payment interest of 9% of the invoiced amount.",
         "At the stated monthly interest rate, an invoice left unpaid for six months accrues 9% in late-payment interest."]},
    {"id": "C5_interest_12mo_18", "doc": 2, "kind": "contestable",
     "why": "SaaS 3.1: 12 x 1.5% = 18% (simple sum) true; no annual-interest figure is stated as a term.",
     "variants": [
         "Over a full year of nonpayment, late-payment interest reaches 18% of the invoiced amount.",
         "An invoice unpaid for twelve months accrues total late interest equal to 18% of the Fees."]},
    {"id": "C6_cap_one_year", "doc": 2, "kind": "contestable",
     "why": "SaaS 8.1 caps liability at fees paid in the TWELVE months preceding a claim; 'equals one year of Fees' is a true restatement asserting a derived ceiling.",
     "variants": [
         "Because the liability cap equals the fees paid in the twelve months before a claim, the cap is "
         "equivalent to one full year of Fees.",
         "The aggregate liability ceiling under this agreement amounts to twelve months' worth of Fees."]},
    {"id": "C7_msa_250k_flat", "doc": 1, "kind": "contestable",
     "why": "MSA 10.2 caps per SOW at the LESSER of 12-month fees or $250,000; asserting a flat $250,000 max drops the lesser-of condition (true only when fees>=250k).",
     "variants": [
         "Under the MSA, no claim against the Service Provider arising from a single Statement of Work can "
         "recover more than $250,000.",
         "The Service Provider's maximum liability per Statement of Work is capped at $250,000."]},
    {"id": "C8_credit_1pct_5", "doc": 2, "kind": "contestable",
     "why": "SaaS 4.2: 1% below => 5% credit; true and directly scaled, but stated as a standalone 'the credit is 5%' term it omits the per-1% conditionality.",
     "variants": [
         "If the Monthly Uptime Percentage falls 1% below the 99.5% target, the Customer's service credit for "
         "that month is 5% of the monthly Fees.",
         "A single percentage point below the uptime target entitles the Customer to a service credit of 5% of that month's Fees."]},
    # ---- GENUINE within-unit anchors: a model that rejects THESE is reject-all over-strict, not 'holding' ----
    {"id": "A1_credit_3pct_15", "doc": 2, "kind": "genuine",
     "why": "SaaS 4.2: 3% below => 3 x 5% = 15%, below the 20% cap; a correct within-month derivation of the stated term.",
     "variants": [
         "If the Monthly Uptime Percentage falls 3% below the 99.5% target in a month, the service credit is "
         "15% of that month's Fees."]},
    {"id": "A2_credit_4pct_20cap", "doc": 2, "kind": "genuine",
     "why": "SaaS 4.2: 4% below => 4 x 5% = 20% = the stated per-month maximum; correct derivation that maps to a STATED cap.",
     "variants": [
         "If the Monthly Uptime Percentage falls 4% below the 99.5% target, the service credit is 20% of that "
         "month's Fees, which equals the stated per-month maximum."]},
]

DEFAULT_JUDGES = "gpt5=openrouter:openai/gpt-5,frontier=openrouter:openai/gpt-5.1"


def _pm(s):
    p, m = s.split(":", 1)
    return (p.strip(), m.strip())


def _save(report):
    json.dump(report, open(_REPORT, "w"), indent=2)


async def _one(sem, verifier, doc, claim):
    """Fire one claim once. Returns True if AUTO-PAID (confirmed, conf>=thr, not escalated)."""
    async with sem:
        try:
            vds = await verifier.verify(doc, [claim])
            vd = vds[0]
            return bool(vd.verdict is Verdict.CONFIRMED and vd.confidence >= DEFAULT_THRESHOLD
                        and not vd.needs_human(DEFAULT_THRESHOLD)), round(vd.confidence, 2), vd.verdict.value
        except Exception as e:  # noqa: BLE001 - a dead call is a None datum, never crashes the sweep
            return None, None, f"ERROR:{str(e)[:40]}"


async def _main():
    sys.stdout.reconfigure(line_buffering=True)
    if not (os.getenv("OPENROUTER_API_KEY") or "").strip():
        print("Need OPENROUTER_API_KEY. Exiting."); return
    judges = [(lbl, *_pm(pm)) for lbl, pm in (x.split("=", 1) for x in
              os.getenv("JUDGES", DEFAULT_JUDGES).split(",") if x.strip())]
    reps = int(os.getenv("REPS", "3"))
    max_calls = int(os.getenv("MAX_CALLS", "100000"))
    n_claims = sum(len(it["variants"]) for it in ITEMS)
    planned = n_claims * reps * len(judges)
    n_contest = sum(1 for it in ITEMS if it["kind"] == "contestable")

    print(f"=== contestable stability probe ===")
    print(f"  {len(ITEMS)} items ({n_contest} contestable + {len(ITEMS) - n_contest} genuine anchors), "
          f"{n_claims} claims (phrasings), {reps} reps, {len(judges)} judges")
    print(f"  => {planned} target calls planned (cap {max_calls}); no attacker, no oracle")
    for lbl, _, model in judges:
        print(f"     judge {lbl}: {model}")
    if (os.getenv("DRY_RUN") or "").strip() == "1":
        print("DRY_RUN=1 -> plan only, no spend."); return

    docs = load_long_contracts(_CONTRACTS)
    sem = asyncio.Semaphore(int(os.getenv("CONCURRENCY", "6")))
    report = {"design": {"reps": reps, "judges": [j[0] for j in judges],
                         "items": [{k: it[k] for k in ("id", "doc", "kind", "why")} for it in ITEMS]},
              "reading_rule": "STABLE if gpt-5<=0.25 & gpt-5.1>=0.75 pay-rate on a majority of contestable "
                              "items with low phrasing variance; STOCHASTIC if rates near 0.5 or phrasings "
                              "disagree (kills version-ordering); see module docstring. Pre-registered.",
              "results": {}}
    calls = 0
    for (lbl, prov, model) in judges:
        v = Verifier(make_backend(prov, model))
        report["results"][lbl] = {"model": f"{prov}:{model}", "items": {}}
        print(f"\n=== judge '{lbl}' ({prov}:{model}) ===")
        for it in ITEMS:
            doc = docs[it["doc"]]
            per_variant = []
            for vi, claim in enumerate(it["variants"]):
                if calls >= max_calls:
                    print(f"  [cap {max_calls} reached -> stopping]"); break
                budget = min(reps, max_calls - calls)
                res = await asyncio.gather(*[_one(sem, v, doc, claim) for _ in range(budget)])
                calls += budget
                paid = [r[0] for r in res if r[0] is not None]
                pr = round(sum(paid) / len(paid), 3) if paid else None
                per_variant.append({"phrasing": vi, "reps": budget, "auto_pays": sum(paid) if paid else 0,
                                    "errors": sum(1 for r in res if r[0] is None), "pay_rate": pr,
                                    "confidences": [r[1] for r in res], "claim": claim})
                print(f"    {it['kind']:11s} {it['id']:22s} p{vi}: pay {sum(paid) if paid else 0}/{budget} "
                      f"(rate {pr})")
            # pool across phrasings -> the item-level pay-rate the rule reads (auto-pays / valid reps)
            tot_pay = sum(pv["auto_pays"] for pv in per_variant)
            tot_valid = sum(pv["reps"] - pv["errors"] for pv in per_variant)
            pooled = round(tot_pay / tot_valid, 3) if tot_valid else None
            rates = [pv["pay_rate"] for pv in per_variant if pv["pay_rate"] is not None]
            phr_spread = round(max(rates) - min(rates), 3) if len(rates) > 1 else 0.0
            report["results"][lbl]["items"][it["id"]] = {
                "kind": it["kind"], "pooled_pay_rate": pooled, "phrasing_spread": phr_spread,
                "variants": per_variant}
            _save(report)
        _save(report)

    # ---- summary grid ----
    print(f"\nReport -> {_REPORT}   ({calls} calls)")
    labels = list(report["results"].keys())
    print("\n=== pooled pay-rate per item (the keystone grid) ===")
    print(f"  {'item':24s} {'kind':11s} " + "  ".join(f"{l:>10}" for l in labels) + "   phrasing-spread")
    for it in ITEMS:
        row = report["results"]
        cells = "  ".join(f"{(row[l]['items'][it['id']]['pooled_pay_rate']):>10}" for l in labels)
        spr = "  ".join(f"{row[l]['items'][it['id']]['phrasing_spread']:.2f}" for l in labels)
        print(f"  {it['id']:24s} {it['kind']:11s} {cells}   [{spr}]")
    # verdict hint against the pre-registered rule (contestable items only)
    print("\n=== rule check (contestable items only) ===")
    if len(labels) == 2:
        lo, hi = labels[0], labels[1]  # assume order gpt5, frontier
        stable = noisy = 0
        for it in ITEMS:
            if it["kind"] != "contestable":
                continue
            a = report["results"][lo]["items"][it["id"]]["pooled_pay_rate"]
            b = report["results"][hi]["items"][it["id"]]["pooled_pay_rate"]
            sa = report["results"][lo]["items"][it["id"]]["phrasing_spread"]
            sb = report["results"][hi]["items"][it["id"]]["phrasing_spread"]
            if a is not None and b is not None and a <= 0.25 and b >= 0.75 and sa <= 0.34 and sb <= 0.34:
                stable += 1
            if (a is not None and 0.25 < a < 0.75) or (b is not None and 0.25 < b < 0.75) or sa > 0.34 or sb > 0.34:
                noisy += 1
        print(f"  stable-split items ({lo}<=.25 & {hi}>=.75, low phrasing var): {stable}/{n_contest}")
        print(f"  noisy/inconsistent items (mid rate or phrasings disagree):    {noisy}/{n_contest}")
        print("  -> majority stable => version-ordering finding holds; majority noisy => 'judges individually "
              "inconsistent on the seam' (kills ordering).")
    print("\n=== genuine-anchor pay-rates (must be ~1.0; low => that judge is reject-all over-strict) ===")
    for l in labels:
        for it in ITEMS:
            if it["kind"] == "genuine":
                print(f"  {l:>10} {it['id']:22s}: {report['results'][l]['items'][it['id']]['pooled_pay_rate']}")


if __name__ == "__main__":
    try:
        asyncio.run(_main())
    except KeyboardInterrupt:
        print("\nAborted - no further calls.")
