"""Hiring policy + Band notification — the market turns scored bids into a team.

This is the hiring stage. `HiringPolicy` is strategy-agnostic: it seeds an RNG
(so Thompson value-sampling in `score_bids` is reproducible for tests), scores the
bids, and delegates team selection to a pluggable `SelectionStrategy`
(`CoverageWithinBudget` now, `KnapsackStrategy` later — both implement the same
interface). `post_hiring` is the side-effecting half: the market announces the
outcome to the Band room, @mentioning the hired workers (declined workers are
not notified). `hire_and_notify` chains the two for the live path.

The split keeps the pure decision (`policy.select`) unit-testable with zero
network, while the Band I/O stays an awaitable seam injected at the boundary.

Budget guard integration
------------------------
``HiringPolicy.select`` accepts an optional ``budget_guard`` kwarg
(``BudgetGuard | None``).  When supplied, the guard's ``check_and_reserve`` is
called WITHOUT an explicit ``projected_usd`` — the guard uses its injected
``project_cost`` callable to estimate the real token cost before committing the
hiring decision.  A BLOCKED decision is returned as an empty ``HiringDecision``
with ``over_budget=True`` and a ``budget_blocked`` reason attached via
``HiringDecision.budget_block_reason``.  When ``budget_guard`` is ``None``
(the default), the behaviour is unchanged — the guard is a strict no-op and all
existing callers continue to work without modification.

Use ``budget_guard_for_job`` to build a guard whose per-task cap equals the
poster's budget and whose ``project_cost`` is the real audit token cost.
"""

from __future__ import annotations

import logging
import random
import time
from decimal import Decimal
from typing import Callable

from ..band.client import BandClient
from ..core.pricing import estimate_cost
from ..payments.budget_guard import BudgetCaps, BudgetGuard
from .hiring_types import Hire, HiringDecision, SelectionStrategy
from .schema import Bid, Job
from .selection import score_bids

logger = logging.getLogger(__name__)

_ZERO_DECIMAL = Decimal("0")


def budget_guard_for_job(
    job: Job,
    *,
    worker_model: str,
    verifier_model: str,
    n_workers: int,
    now: Callable[[], float] | None = None,
) -> BudgetGuard:
    """Build a ``BudgetGuard`` scoped to a single job.

    The global session and daily caps are both set to the poster's budget
    (``job.budget_atomic / 1_000_000`` USD).  Because this guard is instantiated
    fresh for each job, the global caps are the correct enforcement scope — a
    per-task rule would require the task_label to match the pattern, which adds
    unnecessary coupling.  No per-task rules are set.

    The injected ``project_cost`` closure estimates the real audit token cost:
    ``n_workers`` worker passes + one verifier pass, all over ``job.contract``.
    ``estimate_cost`` returns ``None`` for unknown models (treated as 0 by the guard
    — unknown cost is not blocked).

    Args:
        job: The job being hired for (supplies the budget and contract text).
        worker_model: Model name used by each worker agent.
        verifier_model: Model name used by the verifier agent.
        n_workers: Number of worker agents in the roster.
        now: Injected clock (``time.time``-shaped).  Defaults to ``time.time``.

    Returns:
        A ``BudgetGuard`` ready to pass to ``HiringPolicy.select``.
    """
    budget_usd = Decimal(job.budget_atomic) / Decimal("1000000")
    caps = BudgetCaps(
        session_usd=budget_usd,
        daily_usd=budget_usd,
        task_rules=(),
    )

    def _project_cost(**_kwargs: object) -> float:
        worker_cost = n_workers * (estimate_cost(worker_model, job.contract) or 0.0)
        verifier_cost = estimate_cost(verifier_model, job.contract) or 0.0
        return worker_cost + verifier_cost

    return BudgetGuard(
        caps=caps,
        project_cost=_project_cost,
        now=now if now is not None else time.time,
    )


class HiringPolicy:
    """Turns a job's bids into a `HiringDecision` via a pluggable strategy.

    The policy owns the seed (making the strategy's Thompson value samples
    reproducible) and the pure scoring → selection → tally pipeline; it performs
    no I/O. Selection itself is delegated to ``strategy``.
    """

    def __init__(self, strategy: SelectionStrategy, *, seed: int | None = None) -> None:
        """Bind a selection strategy and an optional RNG seed.

        Args:
            strategy: The team-selection strategy (e.g. ``CoverageWithinBudget``).
            seed: Optional RNG seed; fixing it makes Thompson sampling — and thus
                the whole decision — deterministic for tests.
        """
        self.strategy = strategy
        self.seed = seed

    def select(
        self,
        job: Job,
        bids: list[Bid],
        *,
        budget_guard: "BudgetGuard | None" = None,
    ) -> HiringDecision:
        """Score the bids and select a team under the job's budget.

        With no bids, returns an empty decision (no hires, nothing declined,
        zero spend, under budget). Otherwise scores every bid with a seeded RNG,
        hands the scored bids to the strategy, tallies the hires' total price,
        and packages the outcome.

        If ``budget_guard`` is provided, the guard's ``check_and_reserve`` is
        called WITHOUT an explicit ``projected_usd`` — the guard uses its
        injected ``project_cost`` callable to estimate the real token cost
        BEFORE committing any hire.  A BLOCKED verdict returns an empty
        ``HiringDecision`` with ``over_budget=True`` and ``budget_block_reason``
        set.  Passing ``None`` (the default) is a complete no-op — existing
        callers are unaffected.

        Args:
            job: The job being hired for (supplies the budget).
            bids: Candidate bids; may be empty.
            budget_guard: Optional pre-spend circuit breaker.  ``None`` ⇒ no
                guard (current default behaviour is preserved).

        Returns:
            The :class:`HiringDecision` describing who was hired and declined.
        """
        # --- Budget guard pre-check (additive, no-op when guard is None) ------
        if budget_guard is not None:
            # No explicit projected_usd: the guard uses its injected project_cost
            # callable to estimate the real token cost before any LLM call is made.
            decision = budget_guard.check_and_reserve(
                job.job_id,
                task_label=getattr(job, "kind", None),
            )
            if not decision.allowed:
                reason = (
                    f"budget guard blocked: {decision.breached_window} cap "
                    f"${decision.cap_usd} reached (spend ${decision.spend_usd})"
                )
                logger.warning("Job %s blocked by budget guard: %s", job.job_id, reason)
                return HiringDecision(
                    hired=(),
                    declined=tuple(b.worker for b in bids),
                    total_price_atomic=0,
                    budget_atomic=job.budget_atomic,
                    over_budget=True,
                    strategy=self.strategy.name,
                    budget_block_reason=reason,
                )
        # -----------------------------------------------------------------------

        if not bids:
            return HiringDecision(
                hired=(),
                declined=(),
                total_price_atomic=0,
                budget_atomic=job.budget_atomic,
                over_budget=False,
                strategy=self.strategy.name,
            )

        rng = random.Random(self.seed)
        scored = score_bids(bids, rng)
        hired, declined, over_budget = self.strategy.select(scored, job.budget_atomic)
        total = sum(h.price_atomic for h in hired)
        return HiringDecision(
            hired=tuple(hired),
            declined=tuple(declined),
            total_price_atomic=total,
            budget_atomic=job.budget_atomic,
            over_budget=over_budget,
            strategy=self.strategy.name,
        )


async def post_hiring(
    decision: HiringDecision,
    market_band: BandClient,
    room_id: str,
    mention_for: dict[str, dict],
) -> None:
    """Announce a hiring decision to the Band room.

    Posts one @mention message per hired worker ("you're hired"). Only the hired
    are notified — declined workers receive nothing (keeps the room signal clean).
    Workers missing from ``mention_for`` are skipped. A Band error on any single
    post is logged and swallowed so one failure can't abort the rest.

    Args:
        decision: The outcome to announce.
        market_band: The market's Band client (the poster).
        room_id: The room hosting the job.
        mention_for: ``worker -> {"id", "handle", "name"}`` mention payloads.
    """
    for hire in decision.hired:
        mention = mention_for.get(hire.worker)
        if mention is None:
            continue
        price = hire.price_atomic / 1e6
        content = (
            f"@{mention['name']} You're hired — ${price:.4f} for the audit. Begin."
        )
        try:
            await market_band.post_message(room_id, content, mentions=[mention])
        except Exception:
            logger.exception(
                "Band post failed for hire %s in room %s", hire.worker, room_id
            )

    # Only the hired are notified — keeps the room signal clean (no decline spam).
    # A declined worker simply receives no hire message.


async def hire_and_notify(
    job: Job,
    bids: list[Bid],
    market_band: BandClient,
    room_id: str,
    mention_for: dict[str, dict],
    policy: HiringPolicy,
) -> HiringDecision:
    """Run the full live hiring path: decide, then announce to Band.

    Args:
        job: The job to hire for.
        bids: Candidate bids.
        market_band: The market's Band client.
        room_id: The room hosting the job.
        mention_for: ``worker -> {"id", "handle", "name"}`` mention payloads.
        policy: The hiring policy that makes the decision.

    Returns:
        The :class:`HiringDecision` (already announced to the room).
    """
    decision = policy.select(job, bids)
    await post_hiring(decision, market_band, room_id, mention_for)
    return decision
