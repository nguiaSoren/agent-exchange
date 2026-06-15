"""Reputation-loop smoke — WATCH a clean worker's reputation climb and a liar's fall.

This is the fully-OFFLINE demonstration of the market's reputation loop (the math is
local — no Band, no x402, no network, no keys). It seeds a fresh reputation store and
runs a few rounds of one job each, where:

  * `clean`  always delivers a confirmed, grounded finding, and
  * `liar`   always fabricates an unsupported one.

After each round it prints both workers' reputation (success_rate) and a seeded
Thompson draw, so you SEE three things happen at once:

  1. the clean worker's reputation rises toward 1.0;
  2. the liar's reputation decays toward 0.0;
  3. the *hire preference flips* — early on the unproven workers' wide Beta posteriors
     overlap and the draw is noisy, but as the records separate the Thompson sample for
     `clean` reliably beats `liar`'s. Reputation now drives the hire.

The headline fairness point is visible too: the two share every job, so the
no-fabrication payment gate would withhold the WHOLE deliverable each round (collective
$0) — yet reputation is graded PER WORKER, so only the liar's track record falls.

    cd agent-exchange
    .venv/bin/python spikes/reputation_loop_smoke.py
"""

from __future__ import annotations

import os
import random
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from agent_exchange.audit.report import AuditedFinding
from agent_exchange.audit.room_audit_types import RoomAuditResult
from agent_exchange.market.hiring_types import Hire
from agent_exchange.market.reputation import JsonReputationStore
from agent_exchange.market.reputation_loop import apply_outcomes
from agent_exchange.market.selection import thompson_value
from agent_exchange.verify.schema import ClaimVerdict, Verdict
from agent_exchange.workers.finding import Finding

ROUNDS = 3
THOMPSON_SEEDS = 400


def _audited(worker: str, claim: str, verdict: Verdict, idx: int) -> AuditedFinding:
    return AuditedFinding(
        finding=Finding(worker=worker, clause_ref=str(idx), claim=claim, severity="medium"),
        verdict=ClaimVerdict(claim=claim, verdict=verdict, confidence=1.0, reason=""),
    )


def _round_deliverable() -> RoomAuditResult:
    """One job's graded deliverable: `clean` confirms, `liar` fabricates."""
    return RoomAuditResult(
        work_room_id="demo-room",
        audited=(
            _audited("clean", "vendor liability is capped at the prior 12 months' fees", Verdict.CONFIRMED, 0),
            _audited("liar", "the contract grants a secret unilateral 90-day termination", Verdict.UNSUPPORTED, 1),
        ),
        report_summary="",
        report_audited=(),
    )


def _hire(worker: str) -> Hire:
    return Hire(worker=worker, price_atomic=1, value=1.0, relevance=1.0)


def _mean_thompson(record, specialty: str) -> float:
    """Average Thompson draw for a worker over many seeds (its per-specialty posterior)."""
    total = 0.0
    for seed in range(THOMPSON_SEEDS):
        total += thompson_value(record, relevance=1.0, rng=random.Random(seed), specialty=specialty)
    return total / THOMPSON_SEEDS


def _hire_win_rate(clean_rec, liar_rec) -> float:
    """Fraction of seeds where the clean worker's draw beats the liar's (the hire flip)."""
    wins = 0
    for seed in range(THOMPSON_SEEDS):
        c = thompson_value(clean_rec, relevance=1.0, rng=random.Random(seed), specialty="clean")
        l = thompson_value(liar_rec, relevance=1.0, rng=random.Random(seed), specialty="liar")
        if c > l:
            wins += 1
    return wins / THOMPSON_SEEDS


def _print_row(label: str, clean_rec, liar_rec) -> None:
    clean_draw = _mean_thompson(clean_rec, "clean")
    liar_draw = _mean_thompson(liar_rec, "liar")
    win = _hire_win_rate(clean_rec, liar_rec)
    print(
        f"  {label:<8}  "
        f"clean: rep={clean_rec.success_rate:0.3f} draw={clean_draw:0.3f}   "
        f"liar:  rep={liar_rec.success_rate:0.3f} draw={liar_draw:0.3f}   "
        f"P(hire clean)={win:0.0%}"
    )


def main() -> None:
    print("Reputation loop — clean worker vs. fabricator (offline; local math)\n")
    print("Every round both share ONE job. The no-fab gate withholds the WHOLE job (money is")
    print("collective $0), but reputation is per-worker — only the liar's record should fall.\n")

    with tempfile.TemporaryDirectory() as d:
        store = JsonReputationStore(os.path.join(d, "rep.json"))

        # Round 0: both fresh at the neutral 0.5 prior — the hire is a coin-flip.
        _print_row("start", store.get("clean"), store.get("liar"))

        for r in range(1, ROUNDS + 1):
            apply_outcomes(store, _round_deliverable(), [_hire("clean"), _hire("liar")])
            _print_row(f"round {r}", store.get("clean"), store.get("liar"))

        clean = store.get("clean")
        liar = store.get("liar")
        print()
        print(f"  clean worker reputation climbed 0.500 -> {clean.success_rate:0.3f}")
        print(f"  liar    worker reputation fell    0.500 -> {liar.success_rate:0.3f}")
        flip = _hire_win_rate(clean, liar)
        print(f"  the market now hires the clean worker {flip:0.0%} of the time (was ~50% at start).")
        print("\n  The loop is closed: verified outcomes feed reputation, reputation drives the hire.")


if __name__ == "__main__":
    main()
