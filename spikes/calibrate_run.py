"""Calibration loop — runs the verifier over the labeled cases and reports calibration.

Closes the loop once (a) you've labeled the cases (label_calibration.html → labels.json)
and (b) your AI/ML API key is funded. It:
  1. runs the live verifier on every case in data/calibration/cases.json,
  2. compares its verdicts to YOUR gold labels (labels.json),
  3. prints the reliability curve, ECE, and the chosen pay/escalate threshold,
  4. writes data/calibration/calibration_result.json (the §7 hidden-depth artifact).

Run:
  python tools/build_label_html.py          # (already done) → label_calibration.html
  open label_calibration.html               # click through → download labels.json into agent-exchange/
  .venv/bin/python spikes/calibrate_run.py   # after credits activate
"""

from __future__ import annotations

import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import httpx
from dotenv import load_dotenv

from agent_exchange.core import make_backend
from agent_exchange.verify import Verifier, ece, pairs_from, pick_threshold, reliability_curve

load_dotenv()

HERE = os.path.dirname(os.path.abspath(__file__))
CASES_PATH = os.path.join(HERE, "..", "data", "calibration", "cases.json")
LABELS_PATH = os.path.join(HERE, "..", "labels.json")
OUT_PATH = os.path.join(HERE, "..", "data", "calibration", "calibration_result.json")
TARGET_ACCURACY = 0.9


async def main() -> None:
    if not os.path.exists(LABELS_PATH):
        print(f"no labels.json at {LABELS_PATH} — open label_calibration.html, click through, "
              "and download labels.json into agent-exchange/ first.")
        return

    # Provider/model are configurable: default AI/ML API + the verifier model, but you can
    # calibrate on any provider (e.g. CALIB_PROVIDER=openai) that serves the SAME model id.
    provider = os.getenv("CALIB_PROVIDER", "aimlapi")
    model = os.getenv("CALIB_MODEL", os.getenv("AIMLAPI_VERIFIER_MODEL", "gpt-5.1-2025-11-13"))
    try:
        backend = make_backend(provider, model)
    except RuntimeError as e:
        print(e)
        return

    cases = json.load(open(CASES_PATH, encoding="utf-8"))["cases"]
    labels = {row["id"]: row["label"] for row in json.load(open(LABELS_PATH, encoding="utf-8"))["labels"]}
    verifier = Verifier(backend)
    print(f"verifier: {provider} / {model} · {len(cases)} cases · {len(labels)} labels\n")

    predictions: dict[str, tuple[str, float]] = {}
    try:
        for c in cases:
            vs = await verifier.verify(c["contract"], [c["claim"]])
            v = vs[0]
            predictions[c["id"]] = (v.verdict.value, v.confidence)
            agree = "✓" if labels.get(c["id"]) == v.verdict.value else "✗"
            print(f"  {c['id']} {agree} verifier={v.verdict.value:11} conf={v.confidence:.2f}  gold={labels.get(c['id'],'?')}")
    except httpx.HTTPStatusError as e:
        print(f"\nlive call failed: HTTP {e.response.status_code} (key not funded yet?). Try after kickoff.")
        return

    pairs = pairs_from(labels, predictions)
    if not pairs:
        print("\nno usable (prediction,label) pairs — did you label any non-'uncertain' cases?")
        return

    agreement = sum(1 for _, ok in pairs if ok) / len(pairs)
    e = ece(pairs)
    threshold = pick_threshold(pairs, TARGET_ACCURACY)
    print(f"\nagreement (verifier vs you): {agreement:.0%}  ·  ECE: {e:.3f}")
    print(f"pay/escalate threshold @ {TARGET_ACCURACY:.0%} target accuracy: confidence ≥ {threshold:.2f} auto-acts; below → human")
    print("\nreliability curve (bin → mean_conf vs empirical accuracy):")
    for b in reliability_curve(pairs):
        if b.count:
            print(f"  [{b.lo:.1f},{b.hi:.1f})  n={b.count:2d}  conf={b.mean_confidence:.2f}  acc={b.accuracy:.2f}")

    json.dump(
        {"model": model, "n": len(pairs), "agreement": agreement, "ece": e,
         "threshold": threshold, "target_accuracy": TARGET_ACCURACY,
         "pairs": [{"confidence": c, "correct": ok} for c, ok in pairs]},
        open(OUT_PATH, "w", encoding="utf-8"), indent=2,
    )
    print(f"\nwrote {OUT_PATH}")


if __name__ == "__main__":
    asyncio.run(main())
