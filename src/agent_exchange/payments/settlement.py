"""Settlement gate — turn a verified deliverable into per-worker money movement.

`settle_job` is the single bridge between "the work was graded" and "money moved". It
enforces two rules, in this order:

  1. **No-fabrication hard gate.** If ANY claim in the deliverable is `UNSUPPORTED`
     (fabricated / a direct contradiction / an invented fact), the WHOLE job is
     withheld — every worker settles $0, regardless of how good the rest of the work
     was. "$0 for fabricated work" is a hard, all-or-nothing gate, not a prorate.

  2. **Per-worker prorate (x402 `upto` scheme).** On a job that clears the gate, each
     hired worker is paid ``its_bid × pay_fraction`` to its OWN payout wallet, where
     `pay_fraction` is the deliverable's mean per-claim weight under the chosen policy
     (confirmed = full, partial = half under LENIENT). Because x402 lets us settle
     LESS than the authorized maximum, a worker is never paid more than the amount it
     signed for — its bid is a hard ceiling.

Critical ordering invariant: ``verify`` ALWAYS runs before any ``settle``. We validate
each worker's authorization (without moving money) up front and refuse to settle an
authorization that does not verify — even on a job that passed the gate. A worker that
fails verification, has no payout wallet, or whose settle call raises is recorded with a
terminal status and $0 settled; one worker's failure never aborts the others.

This module owns no provider/x402 types: the gate is injected as a `PaymentGate`
Protocol, so the same logic drives the real facilitator-backed gate and the test fake.
"""

from __future__ import annotations

import logging

from ..audit.room_audit_types import RoomAuditResult
from ..market.hiring_types import Hire
from ..verify.schema import LENIENT, SettlementPolicy, Verdict, rule_settlement
from .audit_types import GateEvent, GateHooks
from .types import JobSettlement, PaymentGate, WorkerSettlement

logger = logging.getLogger(__name__)


async def _fire(hooks: GateHooks | None, method: str, ev: GateEvent) -> None:
    """Fire one lifecycle hook by name, but only if `hooks` is present.

    A hook is observation-only: it must NEVER influence or break settlement. So a
    missing `hooks` is a no-op (full backward compatibility), and a hook that raises is
    caught + logged — money movement is unaffected either way.
    """
    if hooks is None:
        return
    fn = getattr(hooks, method, None)
    if fn is None:
        return
    try:
        await fn(ev)
    except Exception:
        logger.exception("gate hook %s raised (ignored — settlement is unaffected)", method)


async def settle_job(
    gate: PaymentGate,
    deliverable: RoomAuditResult,
    hires: list[Hire],
    payout_addresses: dict[str, str],
    *,
    policy: SettlementPolicy = LENIENT,
    hooks: GateHooks | None = None,
    hold_workers: frozenset[str] | set[str] | None = None,
) -> JobSettlement:
    """Settle a graded deliverable into per-worker money movement through the gate.

    Args:
        gate: the injected payment seam (``build_requirement`` / ``authorize`` /
            ``verify`` / ``settle``). Opaque ``requirement``/``payload`` pass-throughs.
        deliverable: the in-room audit result; ``all_audited`` is every specialist
            finding + reporter claim, each carrying the verifier's grade.
        hires: the hired team, in order — each settled to its own wallet for its own bid.
        payout_addresses: ``worker -> payout wallet (0x…)``. A worker missing here has
            no wallet to pay and is withheld.
        policy: verdict→weight policy (default ``LENIENT``: confirmed=1.0, partial=0.5).
        hooks: optional `GateHooks` fired at each lifecycle step (verify ok/fail, before/
            after settle, withhold) for the audit trail. ``None`` (default) ⇒ no hooks
            fire — fully backward compatible. A hook that raises is caught + logged and
            never affects settlement (hooks are observation-only).
        hold_workers: optional set of worker ids to HOLD pending human review — a worker
            whose claim the verifier was too unsure to clear (``needs_human``) is routed
            to a human, so its money is NOT moved here ("awaiting human review", $0
            settled). This is a fail-safe that can only REDUCE payment (never a false
            pay), so it never affects the catch-rate/false-withhold metrics. ``None``
            (default) ⇒ nothing held — fully backward compatible.

    Returns:
        A `JobSettlement`: the gate decision, the prorate fraction actually applied, the
        fabricated-claim count, and one `WorkerSettlement` per hire (in input order).

    Invariants:
        * ``verify`` is ALWAYS called before any ``settle`` (per worker).
        * A single fabricated claim ⇒ ``gate_passed`` is False ⇒ every worker is
          withheld with 0 settled.
        * Each worker's ``settled_atomic`` ≤ its ``authorized_atomic`` (its bid is the
          signed ceiling); on pass it is ``round(bid × pay_fraction)``.
    """
    # The job identity carried on every GateEvent. The deliverable's work room IS the
    # job (one room → one settled job), so its id is the stable per-job key for the trail.
    job_id = deliverable.work_room_id

    # 1. Verdicts + the no-fabrication hard gate. `all_audited` carries ClaimVerdicts
    #    (af.verdict), which is exactly what `rule_settlement` grades.
    verdicts = [af.verdict for af in deliverable.all_audited]
    n_unsupported = sum(v.verdict is Verdict.UNSUPPORTED for v in verdicts)
    gate_passed = n_unsupported == 0

    # 2. Prorate fraction. With no verdicts there is nothing to pay: pay_fraction 0 and
    #    the gate passes vacuously (no fabrication present). On a passing job there are
    #    by construction no unsupported claims, so pay_fraction reflects only the
    #    confirmed=full / partial=half split.
    if not verdicts:
        pay_fraction = 0.0
    else:
        ruling = rule_settlement(verdicts, policy=policy)
        pay_fraction = ruling.pay_fraction

    workers: list[WorkerSettlement] = []

    # 3. Per-worker settlement, in hire order. verify-before-settle is enforced for
    #    every worker; any failure is local (recorded + skipped), never fatal.
    for hire in hires:
        pay_to = payout_addresses.get(hire.worker)

        # No payout wallet ⇒ withheld; we never build a requirement we can't pay to.
        if pay_to is None:
            logger.info("worker %s has no payout address; withholding", hire.worker)
            workers.append(
                WorkerSettlement(
                    worker=hire.worker,
                    pay_to="",
                    authorized_atomic=hire.price_atomic,
                    settled_atomic=0,
                    tx_hash=None,
                    status="withheld",
                )
            )
            await _fire(
                hooks,
                "on_withhold",
                GateEvent(
                    job_id=job_id,
                    event="withheld",
                    worker=hire.worker,
                    authorized_atomic=hire.price_atomic,
                    status="withheld",
                    detail="no payout address",
                ),
            )
            continue

        requirement = gate.build_requirement(amount_atomic=hire.price_atomic, pay_to=pay_to)
        payload = await gate.authorize(requirement)

        # VERIFY UP FRONT — validate the authorization (no money moves) BEFORE any
        # settle. We never settle an authorization that does not verify.
        ok = await gate.verify(payload, requirement)
        if not ok:
            logger.warning("verify failed for worker %s; not settling", hire.worker)
            workers.append(
                WorkerSettlement(
                    worker=hire.worker,
                    pay_to=pay_to,
                    authorized_atomic=hire.price_atomic,
                    settled_atomic=0,
                    tx_hash=None,
                    status="verify_failed",
                )
            )
            fail_ev = GateEvent(
                job_id=job_id,
                event="verify_fail",
                worker=hire.worker,
                authorized_atomic=hire.price_atomic,
                status="verify_failed",
                detail="authorization did not verify",
            )
            await _fire(hooks, "on_after_verify", fail_ev)
            await _fire(hooks, "on_verify_failure", fail_ev)
            continue

        # Authorization verified — the audit trail records a clean verify before settle.
        await _fire(
            hooks,
            "on_after_verify",
            GateEvent(
                job_id=job_id,
                event="verify_ok",
                worker=hire.worker,
                authorized_atomic=hire.price_atomic,
                status="verified",
            ),
        )

        # Gate failed (fabrication anywhere in the deliverable): we DID verify, but we
        # deliberately DO NOT settle — no money for a job containing fabricated work.
        if not gate_passed:
            workers.append(
                WorkerSettlement(
                    worker=hire.worker,
                    pay_to=pay_to,
                    authorized_atomic=hire.price_atomic,
                    settled_atomic=0,
                    tx_hash=None,
                    status="withheld",
                )
            )
            await _fire(
                hooks,
                "on_withhold",
                GateEvent(
                    job_id=job_id,
                    event="withheld",
                    worker=hire.worker,
                    authorized_atomic=hire.price_atomic,
                    status="withheld",
                    detail="job withheld: fabricated claim in deliverable",
                ),
            )
            continue

        # HUMAN-IN-THE-LOOP HOLD — this worker's claim was too unsure to clear
        # (``needs_human``), so it is routed to a human. We DID verify, but we do
        # NOT move money: an escalated claim is held ("awaiting human review"),
        # never auto-paid. A fail-safe withhold (can only reduce pay → never a
        # false pay), independent of the job-level gate. Only a human (out of band)
        # releases it. Empty ``hold_workers`` (the default) skips this entirely.
        if hold_workers and hire.worker in hold_workers:
            workers.append(
                WorkerSettlement(
                    worker=hire.worker,
                    pay_to=pay_to,
                    authorized_atomic=hire.price_atomic,
                    settled_atomic=0,
                    tx_hash=None,
                    status="awaiting human review",
                )
            )
            await _fire(
                hooks,
                "on_withhold",
                GateEvent(
                    job_id=job_id,
                    event="withheld",
                    worker=hire.worker,
                    authorized_atomic=hire.price_atomic,
                    status="awaiting human review",
                    detail="escalated to human (needs_human) — held, not auto-paid",
                ),
            )
            continue

        # Gate passed AND verified: settle the prorated amount, capped at the bid. The
        # bid is the signed maximum, and pay_fraction ∈ [0,1], so amount ≤ bid always.
        amount = int(round(hire.price_atomic * pay_fraction))
        if amount <= 0:
            # The prorate rounded to nothing to pay — withhold rather than settle $0.
            workers.append(
                WorkerSettlement(
                    worker=hire.worker,
                    pay_to=pay_to,
                    authorized_atomic=hire.price_atomic,
                    settled_atomic=0,
                    tx_hash=None,
                    status="withheld",
                )
            )
            await _fire(
                hooks,
                "on_withhold",
                GateEvent(
                    job_id=job_id,
                    event="withheld",
                    worker=hire.worker,
                    authorized_atomic=hire.price_atomic,
                    status="withheld",
                    detail="prorate rounded to zero",
                ),
            )
            continue

        # About to move money — the trail records the intent (amount) before the tx.
        await _fire(
            hooks,
            "on_before_settle",
            GateEvent(
                job_id=job_id,
                event="before_settle",
                worker=hire.worker,
                authorized_atomic=hire.price_atomic,
                settled_atomic=amount,
                status="settling",
            ),
        )

        try:
            tx = await gate.settle(payload, requirement, amount_atomic=amount)
        except Exception:
            # One worker's settle raising must not abort the rest of the team.
            logger.exception("settle failed for worker %s", hire.worker)
            workers.append(
                WorkerSettlement(
                    worker=hire.worker,
                    pay_to=pay_to,
                    authorized_atomic=hire.price_atomic,
                    settled_atomic=0,
                    tx_hash=None,
                    status="settle_failed",
                )
            )
            # A failed settle moved no money — record it as a withhold on the trail.
            await _fire(
                hooks,
                "on_withhold",
                GateEvent(
                    job_id=job_id,
                    event="withheld",
                    worker=hire.worker,
                    authorized_atomic=hire.price_atomic,
                    status="settle_failed",
                    detail="settle call raised",
                ),
            )
            continue

        workers.append(
            WorkerSettlement(
                worker=hire.worker,
                pay_to=pay_to,
                authorized_atomic=hire.price_atomic,
                settled_atomic=amount,
                tx_hash=tx,
                status="settled",
            )
        )
        await _fire(
            hooks,
            "on_after_settle",
            GateEvent(
                job_id=job_id,
                event="settled",
                worker=hire.worker,
                authorized_atomic=hire.price_atomic,
                settled_atomic=amount,
                tx_hash=tx,
                status="settled",
            ),
        )

    # 4. The job-level outcome. pay_fraction is reported as 0 when the gate failed (no
    #    prorate was applied to anyone).
    return JobSettlement(
        gate_passed=gate_passed,
        pay_fraction=pay_fraction if gate_passed else 0.0,
        n_unsupported=n_unsupported,
        workers=tuple(workers),
    )
