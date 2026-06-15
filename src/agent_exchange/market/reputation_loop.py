"""Reputation loop — close the hire→work→verify→reputation cycle.

After a job's deliverable has been graded by the verifier, this module folds each
worker's VERIFIED outcome back into its reputation, so the next hiring round reflects
who actually delivered (not who merely bid well). The reputation store feeds the
Thompson-sampling hiring policy, so a clean track record earns future work and a
fabricator's track record decays.

Outcome model (QUALITY-BASED) — a worker's reputation is graded on ITS OWN findings,
independently of how the job as a whole settled:

  * **success** — the worker delivered work AND none of its own findings was graded
    ``unsupported`` (fabricated). A worker that posted nothing, or that fabricated
    even one claim, is not a success.
  * **pay_fraction** — the verified fraction of the worker's OWN findings:
    ``(n_confirmed + 0.5 * n_partial) / n_findings`` (partials earn LENIENT half
    credit), or ``0.0`` when the worker delivered no findings.

A SECOND, INDEPENDENT cheat-signal — behavioral drift — also gates ``success``. The
verifier judges CONTENT ("is the claim real?"); the drift detector judges BEHAVIOR
("is this agent behaving like itself?" — e.g. it quietly swapped its declared frontier
model for a cheap one). These are decoupled: a worker the drift detector flags has
FAILED the behavioral check regardless of whether its content passed, so its reputation
``success`` becomes ``False`` even if every finding was confirmed. This touches ONLY
reputation — payment stays purely content-based (the verifier/settlement gate is
unchanged); ``pay_fraction`` therefore stays the content fraction, since drift is a
reputation signal, not a content-quality one.

Why this is fair — fabrication and reputation are decoupled on purpose. The payment
gate (elsewhere) is a no-fabrication HARD gate: if ANY worker fabricates a claim, the
WHOLE job is withheld and everyone is paid $0. But reputation is graded per worker on
its own findings, so a CLEAN worker that happened to share a poisoned job keeps its
good reputation and only the FABRICATOR's reputation falls. The shared-job penalty
lands on money (collective, to deter free-riding on a poisoned deliverable); the
reputation penalty lands only on the actual offender.

Evidence anchoring — when a signed receipt and a ledger are supplied, each reputation
update is appended as a ``"reputation_update"`` ledger entry carrying the receipt's
deliverable hash + signer + signature. The reputation delta is then provably backed by
the same key-signed proof-of-work that backed the payment: the track-record change and
the verified deliverable share one anchor.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from ..audit.room_audit_types import RoomAuditResult
from ..payments.audit_types import SignedReceipt
from ..payments.ledger import HashChainedLedger
from ..verify.schema import Verdict
from .hiring_types import Hire
from .schema import ReputationRecord, ReputationStore


@dataclass(frozen=True, slots=True)
class WorkerOutcome:
    """One worker's verified outcome for a single job — the unit the reputation
    store folds in.

    Attributes
    ----------
    worker:
        Worker id (== its specialty; the worker's name and its specialty track are
        the same in this market).
    success:
        True iff the worker delivered at least one finding AND none of its findings
        was graded ``unsupported``. Quality gate: real work, nothing fabricated.
    pay_fraction:
        Verified fraction of the worker's OWN findings,
        ``(n_confirmed + 0.5 * n_partial) / n_findings`` (lenient half credit for
        partials), or ``0.0`` when ``n_findings == 0``.
    n_findings:
        How many of the deliverable's specialist findings this worker contributed.
    n_confirmed, n_partial, n_unsupported:
        The verdict breakdown across this worker's findings.
    drifted:
        True when the behavioral drift detector flagged this worker's run; forces
        ``success=False`` independent of content. A second, independent cheat-signal
        (behavior, not content) — it does NOT affect ``pay_fraction`` (payment stays
        content-based).
    """

    worker: str
    success: bool
    pay_fraction: float
    n_findings: int
    n_confirmed: int
    n_partial: int
    n_unsupported: int
    drifted: bool = False


def worker_outcomes(
    deliverable: RoomAuditResult,
    hires: list[Hire],
    *,
    drift_flags: dict[str, bool] | None = None,
) -> list[WorkerOutcome]:
    """Compute one :class:`WorkerOutcome` per hire from the graded deliverable.

    For each hire, the deliverable's SPECIALIST findings (``deliverable.audited`` —
    NOT the reporter's synthesis, which is not a hired worker's billable work) whose
    ``finding.worker`` matches the hire are gathered and their verdicts counted.

    A worker with zero matching findings still yields a `WorkerOutcome`
    (``success=False``, ``pay_fraction=0.0``): being hired and delivering nothing is
    a recorded, reputation-affecting outcome, not a no-op.

    ``success`` is ``content_success and not drifted`` — the existing content rule
    (``n_findings > 0 and n_unsupported == 0``) AND-ed with the behavioral check. A
    worker the drift detector flagged fails ``success`` even with all-confirmed
    findings. ``pay_fraction`` deliberately stays the CONTENT fraction (it is NOT
    affected by drift): drift is a reputation signal, not a content-quality one, and
    payment is content-based — so a drifted-but-confirmed worker still shows full
    content credit while its ``success`` is ``False``.

    Parameters
    ----------
    deliverable:
        The graded in-room audit result. ``deliverable.audited`` holds the specialist
        findings, each paired with its verifier verdict.
    hires:
        The workers hired for this job (``Hire.worker`` == the specialty/worker id).
    drift_flags:
        Optional ``{worker: flagged}`` map from the behavioral drift detector. A
        truthy flag for a worker forces its ``success`` to ``False`` and sets its
        ``drifted`` field. ``None`` (the default) means no drift signal — behavior is
        then byte-for-byte identical to the content-only rule.

    Returns
    -------
    list[WorkerOutcome]
        One outcome per hire, in hire order.
    """
    outcomes: list[WorkerOutcome] = []
    for hire in hires:
        n_confirmed = n_partial = n_unsupported = 0
        for af in deliverable.audited:
            if af.finding.worker != hire.worker:
                continue
            verdict = af.verdict.verdict
            if verdict is Verdict.CONFIRMED:
                n_confirmed += 1
            elif verdict is Verdict.PARTIAL:
                n_partial += 1
            elif verdict is Verdict.UNSUPPORTED:
                n_unsupported += 1

        n_findings = n_confirmed + n_partial + n_unsupported
        # Content success: delivered real work AND fabricated nothing.
        content_success = n_findings > 0 and n_unsupported == 0
        # Behavioral cheat-signal: the drift detector flagged this worker's run.
        drifted = bool(drift_flags.get(hire.worker)) if drift_flags else False
        # A flagged worker fails the behavioral check regardless of content.
        success = content_success and not drifted
        # Lenient verified fraction of the worker's OWN findings (half credit for
        # partials); 0.0 when the worker delivered nothing. Drift does NOT touch this
        # — payment stays content-based.
        pay_fraction = (
            (n_confirmed + 0.5 * n_partial) / n_findings if n_findings > 0 else 0.0
        )

        outcomes.append(
            WorkerOutcome(
                worker=hire.worker,
                success=success,
                pay_fraction=pay_fraction,
                n_findings=n_findings,
                n_confirmed=n_confirmed,
                n_partial=n_partial,
                n_unsupported=n_unsupported,
                drifted=drifted,
            )
        )
    return outcomes


def apply_outcomes(
    store: ReputationStore,
    deliverable: RoomAuditResult,
    hires: list[Hire],
    receipt: SignedReceipt | None = None,
    *,
    drift_flags: dict[str, bool] | None = None,
    ledger: HashChainedLedger | None = None,
    timestamp: str | None = None,
) -> dict[str, ReputationRecord]:
    """Fold each worker's verified outcome into the reputation store and return the
    new records.

    For every worker outcome the store's ``update`` is called with the worker's own
    success + verified pay fraction, tagged with ``specialty == worker`` so the
    worker's global and per-specialty track records both move. When a signed receipt
    and a ledger are supplied, each update is also anchored as a
    ``"reputation_update"`` ledger entry, so the reputation delta is provably backed
    by the same key-signed receipt that backed the payment.

    Parameters
    ----------
    store:
        The reputation store to fold outcomes into (e.g. ``JsonReputationStore``).
    deliverable:
        The graded in-room audit result (source of the verdicts).
    hires:
        The workers hired for this job.
    receipt:
        Optional signed receipt for the job; its deliverable hash + signer +
        signature anchor each ledger entry. Required for ledger anchoring.
    drift_flags:
        Optional ``{worker: flagged}`` map from the behavioral drift detector,
        threaded into :func:`worker_outcomes`. A flagged worker's ``success`` is
        forced ``False`` (independent of content) and the flag is recorded both on
        the outcome and, when anchored, as ``"drifted"`` in the ledger entry. ``None``
        reproduces the content-only behavior exactly.
    ledger:
        Optional hash-chained ledger to append a ``"reputation_update"`` entry per
        worker. Only written when BOTH ``ledger`` and ``receipt`` are provided.
    timestamp:
        ISO-8601 UTC timestamp for the ledger entries; defaults to "now" (UTC).

    Returns
    -------
    dict[str, ReputationRecord]
        ``{worker: new_record}`` for each updated worker — the NEW reputation after
        folding, so the caller can see exactly how the track record shifted.
    """
    outcomes = worker_outcomes(deliverable, hires, drift_flags=drift_flags)
    anchor_ts = timestamp or datetime.now(timezone.utc).isoformat()

    updated: dict[str, ReputationRecord] = {}
    for o in outcomes:
        # The worker's name IS its specialty, so the per-specialty track updates too.
        store.update(
            o.worker,
            success=o.success,
            pay_fraction=o.pay_fraction,
            specialty=o.worker,
        )
        new_record = store.get(o.worker)
        updated[o.worker] = new_record

        if ledger is not None and receipt is not None:
            ledger.append(
                "reputation_update",
                {
                    "worker": o.worker,
                    "success": o.success,
                    "drifted": o.drifted,
                    "pay_fraction": o.pay_fraction,
                    "new_success_rate": new_record.success_rate,
                    "evidence": {
                        "deliverable_hash": receipt.receipt.deliverable_hash,
                        "signer": receipt.signer_address,
                        "signature": receipt.signature,
                    },
                },
                timestamp=anchor_ts,
            )

    return updated
