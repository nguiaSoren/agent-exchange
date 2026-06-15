"""LIVE seeded-liar catch-rate — the one paid run behind the headline catch-rate number.

The offline proof lives in `tests/test_catch_rate.py` (the confusion matrix is exact on a
scripted backend, no network). This spike is its on-network counterpart: it runs the REAL
verifier against a labelled set of fabricated + genuine claims and prints the honest
confusion matrix — catch-rate (fabrications caught), false-withhold rate (good work
wrongly rejected), precision, and calibration (ECE / threshold).

It is NOT run by the test suite — the orchestrator runs it by hand once a model provider
is configured:

    python3 spikes/catch_rate_run.py

Env contract (read from `.env`):
  - `OPENAI_API_KEY` — the model brain for BOTH generating the labelled set and verifying
    it. With it UNSET the spike prints a hint and exits cleanly (never spends).
  - `OPENAI_VERIFIER_MODEL` — the verifier model (default `gpt-4.1`, a strong model — the
    verifier is the trust anchor, so it gets the better model).
  - `OPENAI_GEN_MODEL` — the model that GENERATES the seeded liar/genuine claims
    (default `gpt-4.1-mini`; only used when the fixture has to be built the first time).
  - `CATCH_RATE_N` — target number of generated labelled claims (default 200).
  - `CATCH_RATE_FIXTURE` — fixture path (default `data/eval/seeded_liar_fixture.json`).
    The labelled set is generated ONCE and cached here; later runs reuse it (so the
    fixture is stable and only the verifier re-runs).

Flow: load (or generate-once + save) the fixture, fold in the 24-case calibration gold,
run the real verifier over the whole set, print `format_report`, and write the full report
to `data/eval/catch_rate_report.json`. Never crashes, never spends without a key.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from dataclasses import asdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from dotenv import load_dotenv

from agent_exchange.core import make_backend
from agent_exchange.eval.catch_rate import format_report, run_catch_rate
from agent_exchange.eval.seeded_liar import (
    generate_labeled_claims,
    gold_claims_from_calibration,
    load_fixture,
    save_fixture,
)
from agent_exchange.verify import Verifier

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Explicit path — load_dotenv() with no path can fail depending on cwd. Env is read
# lazily by make_backend at call time, so loading it after the imports is fine.
load_dotenv(os.path.join(_ROOT, ".env"))

_DEFAULT_FIXTURE = os.path.join(_ROOT, "data", "eval", "seeded_liar_fixture.json")
_CALIB_CASES = os.path.join(_ROOT, "data", "calibration", "cases.json")
_REPORT_PATH = os.path.join(_ROOT, "data", "eval", "catch_rate_report.json")


async def _main() -> None:
    if not (os.getenv("OPENAI_API_KEY") or "").strip():
        print(
            "OPENAI_API_KEY is not set — the live catch-rate run needs a model provider. "
            "Add it to .env and re-run. Exiting without spending."
        )
        return

    verifier_model = os.getenv("OPENAI_VERIFIER_MODEL", "gpt-4.1")
    gen_model = os.getenv("OPENAI_GEN_MODEL", "gpt-4.1-mini")
    n_target = int(os.getenv("CATCH_RATE_N", "200"))
    fixture_path = os.getenv("CATCH_RATE_FIXTURE", _DEFAULT_FIXTURE)

    # 1. the labelled set: reuse the cached fixture, or generate it ONCE and save it.
    if os.path.exists(fixture_path):
        claims = load_fixture(fixture_path)
        print(f"Loaded {len(claims)} labelled claims from cached fixture {fixture_path}")
    else:
        print(
            f"No fixture at {fixture_path} — generating {n_target} labelled claims "
            f"with {gen_model} (one-time; cached for future runs)..."
        )
        claims = await generate_labeled_claims(
            make_backend("openai", gen_model), n_target=n_target
        )
        os.makedirs(os.path.dirname(fixture_path) or ".", exist_ok=True)
        save_fixture(claims, fixture_path)
        print(f"  generated + cached {len(claims)} claims → {fixture_path}")

    # 2. fold in the 24-case calibration gold (the hand-labelled hard cases).
    gold = gold_claims_from_calibration(_CALIB_CASES)
    cases = list(claims) + list(gold)
    n_fab = sum(c.label == "fabricated" for c in cases)
    n_gen = sum(c.label == "genuine" for c in cases)
    print(
        f"\nLabelled set: {len(cases)} claims "
        f"({len(claims)} generated + {len(gold)} calibration gold) — "
        f"{n_fab} fabricated / {n_gen} genuine."
    )

    # 3. the cost heads-up — one verifier call per claim (the verifier batches per
    # contract, but generated claims have distinct contracts → ~one call each).
    print(
        f"Estimated verifier calls: ~{len(cases)} (model {verifier_model}). "
        "This spends real money. Ctrl-C now to abort."
    )

    # 4. run the REAL verifier over the whole labelled set.
    verifier = Verifier(make_backend("openai", verifier_model))
    report = await run_catch_rate(cases, verifier)

    # 5. print + persist the honest confusion matrix.
    print("\n" + format_report(report))
    os.makedirs(os.path.dirname(_REPORT_PATH) or ".", exist_ok=True)
    with open(_REPORT_PATH, "w") as f:
        json.dump(asdict(report), f, indent=2)
    print(f"\nFull report written to {_REPORT_PATH}")


if __name__ == "__main__":
    try:
        asyncio.run(_main())
    except KeyboardInterrupt:
        print("\nAborted by user — no further calls made.")
