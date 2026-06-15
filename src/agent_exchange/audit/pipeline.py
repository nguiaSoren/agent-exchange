"""The end-to-end contract-audit pipeline: workers → verifier → settlement → trace.

`audit()` is the one orchestration seam that ties the three locked subsystems together:

  1. **deliver** — the `AuditPool` fans specialists out over the contract and returns
     a flat list of `Finding`s (each finding's `claim` is the checkable assertion).
  2. **verify** — the `Verifier` grades every claim against the contract text, returning
     one `ClaimVerdict` per claim, order-aligned with the findings it was handed.
  3. **settle** — `rule_settlement` maps the verdicts → a `SettlementRuling` (a pay
     fraction + an escalate flag) under the chosen `SettlementPolicy`, and the pipeline
     converts that fraction into a concrete settled/withheld split of the authorized amount.

The pipeline owns NO business policy of its own: thresholds and the verdict→payment
weighting live in `verify.schema`, and the pool/verifier own delivery and grading. Its
job is to (a) thread the stages in order, (b) keep the finding↔verdict zip safe, (c) turn
the ruling into money under the JobTrace invariant, and (d) — when a `writer` is given —
emit ONE immutable `JobTrace` row so the headline metric ("$X settled, $0 for fabricated
work, N false claims caught & withheld") is *measured*, not invented.

Money invariant (enforced by `JobTrace.__post_init__`): the settled amount is paid only
when the ruling earns a positive fraction AND nothing was escalated to a human; otherwise
$0 is settled and the full authorized amount is withheld. In every case
`withheld == authorized - settled`.
"""

from __future__ import annotations

from ..metrics import (
    ClaimRecord,
    JobTrace,
    StageTimings,
    TraceWriter,
    monotonic_ns,
)
from ..verify.schema import (
    DEFAULT_POLICY,
    DEFAULT_THRESHOLD,
    ClaimVerdict,
    SettlementPolicy,
    Verdict,
    rule_settlement,
)
from ..verify.verifier import Verifier
from ..workers.pool import AuditPool
from .report import AuditedFinding, AuditReport


async def audit(
    contract: str,
    *,
    contract_id: str,
    pool: AuditPool,
    verifier: Verifier,
    threshold: float = DEFAULT_THRESHOLD,
    policy: SettlementPolicy = DEFAULT_POLICY,
    authorized_atomic: int = 0,
    writer: TraceWriter | None = None,
) -> AuditReport:
    """Run one contract through deliver → verify → settle and return an `AuditReport`.

    Parameters
    ----------
    contract:
        The full contract text every specialist reads and every claim is graded against.
    contract_id:
        Stable id for this audit. Used as the report's id and (when tracing) as the
        `JobTrace.job_id` / `job_spec` (so same-id runs are tamper-evidently linkable).
    pool:
        The `AuditPool` whose `run(contract)` fans specialists out and returns findings.
    verifier:
        The `Verifier` whose `verify(contract, claims)` grades the findings' claims,
        returning one `ClaimVerdict` per claim in the SAME order as the claims handed in.
    threshold:
        Confidence floor below which a claim escalates to a human (passed to
        `rule_settlement`). Defaults to the verifier's `DEFAULT_THRESHOLD`.
    policy:
        The verdict→payment weighting (`STRICT` by default — a partial/unsupported claim
        earns $0). Passed straight to `rule_settlement`.
    authorized_atomic:
        What the buyer authorized up front, in USDC atomic units (1 USDC == 1_000_000).
        The settled amount is a fraction of this; the remainder is withheld.
    writer:
        Optional append-only `TraceWriter`. When given, exactly one immutable `JobTrace`
        row is written for this audit. When `None`, no trace is emitted (the report is
        still fully returned).

    Returns
    -------
    AuditReport
        `contract_id`, the `audited` findings (finding + verdict, order-aligned), the
        `SettlementRuling`, and per-stage `timings_ms` (`deliver` / `verify`).

    Notes
    -----
    Empty deliverable (no findings) is a normal path: `claims` is empty, the verifier
    returns no verdicts, `rule_settlement([])` yields `pay_fraction == 0`, and nothing
    settles. The settled amount is paid only when the ruling earns a positive fraction
    AND did not escalate; otherwise the full authorized amount is withheld. The
    `JobTrace` money invariant `withheld == authorized - settled` always holds.
    """
    # 1. deliver — fan the specialists out over the contract.
    start = monotonic_ns()
    findings = await pool.run(contract)
    deliver_ns = monotonic_ns()

    # 2. verify — grade every claim, order-aligned with `findings`.
    claims = [f.claim for f in findings]
    verdicts = await verifier.verify(contract, claims)
    verify_ns = monotonic_ns()

    # Defensive alignment guard: the verifier contract is one verdict per claim, in
    # order — but if that ever drifts (short/over-long list), keep the zip total and
    # the report well-formed rather than silently dropping or mispairing findings.
    if len(verdicts) != len(findings):
        verdicts = list(verdicts[: len(findings)])
        verdicts += [
            _fail_safe_verdict(f.claim)
            for f in findings[len(verdicts) :]
        ]

    # 3. pair each finding with its grade.
    audited = tuple(AuditedFinding(f, v) for f, v in zip(findings, verdicts))

    # 4. settle — verdicts → a payment ruling under `policy`.
    ruling = rule_settlement(
        [af.verdict for af in audited], threshold=threshold, policy=policy
    )

    # 5. per-stage latency (monotonic; never wall clock).
    timings_ms = {
        "deliver": (deliver_ns - start) / 1e6,
        "verify": (verify_ns - deliver_ns) / 1e6,
    }

    # 6. turn the pay fraction into a concrete settled/withheld split. Money moves only
    #    when the ruling earns something AND nothing was escalated to a human.
    settled_atomic = (
        round(authorized_atomic * ruling.pay_fraction)
        if (ruling.pay_fraction > 0 and not ruling.escalate)
        else 0
    )
    settled = settled_atomic > 0
    withheld = authorized_atomic - settled_atomic  # JobTrace invariant: == authorized - settled

    # 7. emit exactly one immutable JobTrace row (only when a writer is supplied).
    if writer is not None:
        trace = JobTrace(
            job_id=contract_id,
            job_kind="contract-clause-audit",
            job_spec=contract_id,
            worker_ids=tuple(sorted({f.worker for f in findings})),
            claims=tuple(
                ClaimRecord(
                    worker_id=af.finding.worker,
                    claim_text=af.finding.claim,
                    verdict=af.verdict.verdict.value,
                    confidence=af.verdict.confidence,
                )
                for af in audited
            ),
            amount_authorized_atomic=authorized_atomic,
            amount_settled_atomic=settled_atomic,
            amount_withheld_atomic=withheld,
            settled=settled,
            tx_hash=None,
            seeded_liar=False,
            timings=StageTimings(
                started_ns=start,
                deliver_ns=deliver_ns,
                verify_ns=verify_ns,
                settle_ns=verify_ns if settled else None,
            ),
            seed=0,
        )
        writer.write(trace)

    # 8. the end-to-end report.
    return AuditReport(
        contract_id=contract_id,
        audited=audited,
        ruling=ruling,
        timings_ms=timings_ms,
        total_cost_usd=None,
    )


def _fail_safe_verdict(claim: str) -> ClaimVerdict:
    """Build a withhold+escalate verdict for a finding the verifier under-returned a
    grade for (defensive padding only — the verifier contract makes this unreachable).

    Mirrors the verifier's own fail-safe stance: an ungraded claim NEVER auto-pays —
    it is marked UNSUPPORTED at confidence 0.0, which both withholds (zero weight under
    any policy) and escalates (below any sane threshold) to a human.
    """
    return ClaimVerdict(
        claim=claim,
        verdict=Verdict.UNSUPPORTED,
        confidence=0.0,
        reason="verifier returned fewer verdicts than claims; failing safe → withhold + human review",
        evidence_quote=None,
    )
