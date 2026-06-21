"""Third independent-vendor adjudicator over the contested-zone claims.

Adds a Google Gemini adjudicator (via OpenRouter) to the existing opus-4-8 + gpt-5.5 panel, to
(a) strengthen cross-vendor independence beyond a same-pair, and (b) make a 3-rater Fleiss' kappa
the correct agreement statistic (two raters only support Cohen's kappa / raw agreement). Reads
`contested_audit.json`, adds `gemini_verdict` per claim, and reports: 3-way raw agreement,
Fleiss' kappa (3 raters), unanimous-3 and majority real-leak counts, and Cohen's kappa for the
original opus--gpt pair (chance-corrected, since the base rate of UNSUPPORTED is high). Writes
`data/eval/contested_audit_3vendor.json`. No LLM spend on the existing two vendors (re-uses their
frozen verdicts); only the Gemini calls are live (~$0.5, OpenRouter).

Env: OPENROUTER_API_KEY; AUDIT_GEMINI (default google/gemini-3.1-pro-preview, Google's frontier
model as of 2026-06; a recent independent frontier peer to opus-4-8 + gpt-5.5).
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

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(_ROOT, ".env"))
GEM = os.getenv("AUDIT_GEMINI", "google/gemini-3.1-pro-preview")

_SYS = "You are a strict contract adjudicator. Judge only against the supplied contract text."


def _user(doc: str, claim: str) -> str:
    return (
        f"CONTRACT:\n\"\"\"\n{doc.strip()}\n\"\"\"\n\nCLAIM: {claim}\n\n"
        "Judging ONLY against the contract text, is this claim SUPPORTED (the text states it, or "
        "it follows directly and uncontroversially from what the text states) or UNSUPPORTED (it "
        "relies on inference, outside authority, or scope the text does not state)? "
        "Reply with exactly one word: SUPPORTED or UNSUPPORTED."
    )


def _load():
    audit = json.load(open(os.path.join(_ROOT, "data/eval/contested_audit.json")))["claims"]
    corpus = json.load(open(os.path.join(_ROOT, "data/eval/long_contracts_real.json")))["contracts"]
    report = json.load(open(os.path.join(_ROOT, "data/eval/scaled_adaptive_report.json")))
    prev2full = {c.strip()[:80]: c for c in corpus}
    cfgres = {n: c["results"] for n, c in report["configs"].items() if not c.get("skipped")}
    return audit, prev2full, cfgres


def _contract(cid: str, cfg: str, prev2full, cfgres) -> str | None:
    docidx = int(cid.split("_")[-2])
    prev = cfgres[cfg][docidx]["document_preview"]
    return prev2full.get(prev[:80])


def _norm(v):
    if not v:
        return None
    up = v.upper()
    if "UNSUPPORTED" in up:
        return "UNSUPPORTED"
    if "SUPPORTED" in up:
        return "SUPPORTED"
    return None


def _fleiss_kappa(rows):
    # rows: list of (n_supported, n_unsupported) per item, each summing to N raters
    N = rows[0][0] + rows[0][1]
    n = len(rows)
    Pi = [ (s * s + u * u - N) / (N * (N - 1)) for s, u in rows ]
    P_bar = sum(Pi) / n
    tot = N * n
    p_s = sum(s for s, _ in rows) / tot
    p_u = sum(u for _, u in rows) / tot
    P_e = p_s * p_s + p_u * p_u
    return (P_bar - P_e) / (1 - P_e) if (1 - P_e) else 1.0, P_bar, P_e


def _cohen_kappa(pairs):
    # pairs: list of (a, b) verdicts
    n = len(pairs)
    po = sum(1 for a, b in pairs if a == b) / n
    cats = ["SUPPORTED", "UNSUPPORTED"]
    pe = sum((sum(1 for a, _ in pairs if a == c) / n) * (sum(1 for _, b in pairs if b == c) / n) for c in cats)
    return (po - pe) / (1 - pe) if (1 - pe) else 1.0, po, pe


async def main() -> None:
    audit, prev2full, cfgres = _load()
    backend = make_backend("openrouter", GEM)
    sem = asyncio.Semaphore(4)

    async def one(c):
        async with sem:
            doc = _contract(c["custom_id"], c["config"], prev2full, cfgres)
            if not doc:
                return None
            msgs = [Message.system(_SYS), Message.user(_user(doc, c["claim"]))]
            for attempt in range(4):
                try:
                    r = await backend.complete(msgs, temperature=0.0, max_tokens=512)
                    v = _norm(r.text)
                    if v:
                        return v
                    print(f"  [empty {c['custom_id']}] text={(r.text or '')[:40]!r} attempt={attempt}")
                except Exception as e:  # noqa: BLE001
                    print(f"  [err {c['custom_id']}] {type(e).__name__}: {str(e)[:90]} attempt={attempt}")
                await asyncio.sleep(1.5 * (attempt + 1))
            return None

    print(f"Adjudicating {len(audit)} contested claims with {GEM} (OpenRouter)...")
    verdicts = await asyncio.gather(*[one(c) for c in audit])
    for c, v in zip(audit, verdicts):
        c["gemini_verdict"] = v
    out = os.path.join(_ROOT, "data/eval/contested_audit_3vendor.json")
    json.dump({"gemini_model": GEM, "claims": audit}, open(out, "w"), indent=2)

    # stats over claims with all 3 verdicts present
    three = [(c["opus_verdict"], c["gpt_verdict"], c["gemini_verdict"]) for c in audit
             if _norm(c.get("opus_verdict")) and _norm(c.get("gpt_verdict")) and c.get("gemini_verdict")]
    rows = [(sum(1 for x in t if x == "SUPPORTED"), sum(1 for x in t if x == "UNSUPPORTED")) for t in three]
    raw3 = sum(1 for t in three if t[0] == t[1] == t[2]) / len(three)
    fk, pbar, pe = _fleiss_kappa(rows)
    unanim = sum(1 for t in three if all(x == "UNSUPPORTED" for x in t))
    major = sum(1 for t in three if sum(1 for x in t if x == "UNSUPPORTED") >= 2)
    # original pair (opus, gpt) over the same claims
    pairs = [(c["opus_verdict"], c["gpt_verdict"]) for c in audit if _norm(c.get("opus_verdict")) and _norm(c.get("gpt_verdict"))]
    ck, po, pe2 = _cohen_kappa(pairs)
    gem_n = sum(1 for c in audit if c.get("gemini_verdict"))
    print(f"\n=== THIRD-VENDOR ({GEM}) ===")
    print(f"  Gemini answered: {gem_n}/{len(audit)}")
    print(f"  3-rater claims (all verdicts present): {len(three)}")
    print(f"  3-way RAW agreement (all three identical): {100*raw3:.1f}%")
    print(f"  Fleiss' kappa (3 raters, 2 cats): {fk:.3f}  (P_bar={pbar:.3f}, P_e={pe:.3f})")
    print(f"  Confirmed real leaks, UNANIMOUS 3/3 UNSUPPORTED: {unanim}/{len(three)}")
    print(f"  Confirmed real leaks, MAJORITY >=2/3 UNSUPPORTED: {major}/{len(three)}")
    print(f"  [original pair] opus--gpt Cohen's kappa: {ck:.3f}  (raw agree {100*po:.1f}%, P_e={pe2:.3f})")
    print(f"\n  -> {out}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nAborted.")
