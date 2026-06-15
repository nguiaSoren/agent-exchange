"""LIVE NDA-review run — the SAME marketplace mechanism, a second job type.

The contract audit and the NDA review share every piece of machinery: a registry of job
types, a document-generic verifier (routed by `document_label`), the seeded-liar
catch-rate harness, and the deliver → verify → settle audit pipeline. Only the DATA
differs — the NDA roster, the NDA sample document, and the NDA calibration gold. This
spike proves that, on-network, against a real model.

Two modes in one script (both gated on `OPENAI_API_KEY`; neither spends without it):

  (a) NDA CATCH-RATE — run the REAL verifier (document_label="NDA") over the hand-labeled
      NDA calibration gold and print the honest confusion matrix — catch-rate,
      false-withhold rate, precision, calibration. The NDA counterpart to
      `spikes/catch_rate_run.py`. (The seeded-liar GENERATOR is contract-snippet-bound,
      so the NDA set is the 22 hand-labeled gold cases — already a strong, defensible
      ground truth covering all six NDA areas.)

  (b) ROUTED AUDIT (optional) — build the NDA specialist roster via
      `roster_for("nda-review", ...)`, run the audit pipeline over `SAMPLE_NDA`, verify
      with the NDA verifier, and print the verified findings + settlement. The SAME
      `audit()` seam that handles a contract, now carrying an NDA — routed purely by
      job kind.

It is NOT run by the test suite — the orchestrator runs it by hand once a model provider
is configured:

    python3 spikes/nda_job_run.py

Env contract (read from `.env`):
  - `OPENAI_API_KEY` — the model brain for generating, verifying, and auditing. With it
    UNSET the spike prints a hint and exits cleanly (NEVER spends).
  - `OPENAI_VERIFIER_MODEL` — the verifier model (default `gpt-4.1`; the verifier is the
    trust anchor, so it gets the stronger model).
  - `OPENAI_MODEL` — the model the specialist roster runs on (default `gpt-4.1-mini`).
  - `NDA_ROUTED_AUDIT` — set truthy (`1`/`true`/`yes`) to ALSO run mode (b), the routed
    NDA audit over `SAMPLE_NDA` (default off — catch-rate only).

Flow: print which job kind is running, run the NDA catch-rate over the gold, print
`format_report` + persist it; then, if requested, run the routed NDA audit and print the
verified findings + settlement. Never crashes, never spends without a key.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from dataclasses import asdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from dotenv import load_dotenv

from agent_exchange.audit.pipeline import audit
from agent_exchange.core import make_backend
from agent_exchange.eval.catch_rate import format_report, run_catch_rate
from agent_exchange.eval.seeded_liar import gold_claims_from_calibration
from agent_exchange.verify import Verdict, Verifier
from agent_exchange.workers.job_types import document_label_for, roster_for
from agent_exchange.workers.nda_specialists import SAMPLE_NDA
from agent_exchange.workers.pool import AuditPool

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Explicit path — load_dotenv() with no path can fail depending on cwd. Env is read
# lazily by make_backend at call time, so loading it after the imports is fine.
load_dotenv(os.path.join(_ROOT, ".env"))

_NDA_KIND = "nda-review"
_NDA_CASES = os.path.join(_ROOT, "data", "calibration", "nda_cases.json")
_REPORT_PATH = os.path.join(_ROOT, "data", "eval", "nda_catch_rate_report.json")


def _truthy(name: str) -> bool:
    return (os.getenv(name) or "").strip().lower() in {"1", "true", "yes", "on"}


def _verdict_label(v: Verdict) -> str:
    return {
        Verdict.CONFIRMED: "confirmed",
        Verdict.PARTIAL: "partial",
        Verdict.UNSUPPORTED: "unsupported",
    }[v]


async def _catch_rate(verifier_model: str) -> None:
    """Mode (a): NDA catch-rate over the hand-labeled gold."""
    # the hand-labeled NDA calibration gold (the hard cases).
    cases = gold_claims_from_calibration(_NDA_CASES)
    n_fab = sum(c.label == "fabricated" for c in cases)
    n_gen = sum(c.label == "genuine" for c in cases)
    print(
        f"\nNDA labeled set: {len(cases)} calibration gold claims — "
        f"{n_fab} fabricated / {n_gen} genuine."
    )

    # 3. cost heads-up — one verifier call per distinct contract (gold contracts are
    #    distinct → ~one call each).
    print(
        f"Estimated verifier calls: ~{len(cases)} (model {verifier_model}, "
        'document_label="NDA"). This spends real money. Ctrl-C now to abort.'
    )

    # 4. run the REAL NDA verifier over the whole labeled set.
    verifier = Verifier(make_backend("openai", verifier_model), document_label="NDA")
    report = await run_catch_rate(cases, verifier)

    # 5. print + persist the honest confusion matrix.
    print("\n" + format_report(report))
    os.makedirs(os.path.dirname(_REPORT_PATH) or ".", exist_ok=True)
    with open(_REPORT_PATH, "w") as f:
        json.dump(asdict(report), f, indent=2)
    print(f"\nFull NDA report written to {_REPORT_PATH}")


async def _routed_audit(audit_model: str, verifier_model: str) -> None:
    """Mode (b): the routed NDA audit — the SAME audit() seam, carrying an NDA."""
    print("\n" + "=" * 60)
    print(f"ROUTED AUDIT — job_kind={_NDA_KIND} over SAMPLE_NDA")
    print("=" * 60)

    # Build the NDA roster purely by job kind — same factory the contract audit uses.
    roster = roster_for(_NDA_KIND, "openai", audit_model)
    pool = AuditPool(roster)
    verifier = Verifier(
        make_backend("openai", verifier_model),
        document_label=document_label_for(_NDA_KIND),
    )
    print(f"  roster: {', '.join(w.name for w in roster)}")

    report = await audit(
        SAMPLE_NDA,
        contract_id="sample-nda-routed",
        pool=pool,
        verifier=verifier,
    )

    print(f"\nVERIFIED FINDINGS ({len(report.audited)}):")
    if report.audited:
        for af in report.audited:
            v = af.verdict
            ref = af.finding.clause_ref or "—"
            print(
                f"  • [{af.finding.worker:<14}] ({_verdict_label(v.verdict)}, "
                f"conf={v.confidence:.2f}, clause {ref}) {af.finding.claim}"
            )
    else:
        print("  (no findings posted)")

    r = report.ruling
    print(
        f"\nSETTLEMENT ({r.policy}): pay_fraction={r.pay_fraction:.2f}, "
        f"escalate={r.escalate} | confirmed={r.n_confirmed} partial={r.n_partial} "
        f"unsupported={r.n_unsupported} escalated={r.n_escalated}"
    )
    print(
        f"\nRESULT: the SAME marketplace mechanism graded an NDA — "
        f"{r.n_unsupported} unsupported (caught + unpayable)."
    )


async def _main() -> None:
    if not (os.getenv("OPENAI_API_KEY") or "").strip():
        print(
            "OPENAI_API_KEY is not set — the live NDA run needs a model provider. "
            "Add it to .env and re-run. Exiting without spending."
        )
        return

    verifier_model = os.getenv("OPENAI_VERIFIER_MODEL", "gpt-4.1")
    audit_model = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")

    print(f"Running job_kind={_NDA_KIND} (document_label={document_label_for(_NDA_KIND)!r}).")

    # Mode (a): the NDA catch-rate (always).
    await _catch_rate(verifier_model)

    # Mode (b): the routed NDA audit (optional).
    if _truthy("NDA_ROUTED_AUDIT"):
        await _routed_audit(audit_model, verifier_model)
    else:
        print(
            "\n(Routed audit skipped — set NDA_ROUTED_AUDIT=1 to also run the routed "
            "NDA audit over SAMPLE_NDA through the same audit() pipeline.)"
        )


if __name__ == "__main__":
    try:
        asyncio.run(_main())
    except KeyboardInterrupt:
        print("\nAborted by user — no further calls made.")
