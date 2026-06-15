"""Process-global guards for the public LIVE marketplace run (``POST /api/run`` mode=live).

A LIVE run is the dramatic demo: real Band rooms, real model spend, a real x402
settlement on Base Sepolia. That makes it expensive and serially fragile — a judge
hammering "run it live" must never (a) start two real runs at once (concurrent Band
rooms + concurrent wallet authorizations), nor (b) drain the day's provider/testnet
budget. So the live path is gated by THREE process-global guards, all enforced BEFORE
any streaming or spend begins:

  1. **Single-flight** — only ONE live run may execute at a time. A second live request
     while one is in flight is refused with ``live_busy`` (429). SIM mode is unrestricted
     (no spend, fully deterministic). The flag is released in a ``finally`` so an error or
     a client disconnect can never wedge the lock.
  2. **Daily run-count cap** — at most :data:`LIVE_DAILY_RUNS` live runs per UTC day.
     Over the cap → ``live_cap_reached`` (429). Counted at acquire time (a started run
     consumes a slot even if it later fails — the spend already happened).
  3. **Daily $ cap** — a :class:`BudgetGuard` (the same reserve→reconcile circuit breaker
     the audit endpoint uses) caps total projected live spend per UTC day at
     :data:`LIVE_DAILY_CAP_USD`. Over the cap → ``live_cap_reached`` (429).

The two caps are module constants so a demo can tune them in one place. The whole thing
is a thin singleton (``get_live_guard``) so all requests share one counter/lock/budget;
restarting the process resets it (acceptable for a demo — only a per-day ceiling while up).

This mirrors :mod:`demo_budget` (the audit endpoint's $ cap) but adds the single-flight
lock + run-count cap the live path additionally needs.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

from agent_exchange.payments.budget_guard import BudgetCaps, BudgetGuard

# ---------------------------------------------------------------------------
# The caps. Tune here.
# ---------------------------------------------------------------------------

#: Max LIVE runs per UTC day across ALL callers combined. A started run consumes a
#: slot (the real spend already happened) even if it later errors.
LIVE_DAILY_RUNS: int = 30

#: Max total projected LIVE spend per UTC day (USD), across ALL callers combined.
#: Each live run reserves its projected budget against this; over it → 429.
LIVE_DAILY_CAP_USD: Decimal = Decimal("3.00")

#: A stable label so all live reservations share one daily window in the BudgetGuard.
LIVE_TASK_LABEL = "api_run_live"


def _utc_day() -> str:
    """The current UTC calendar day as an ISO date string (the run-count bucket key)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


@dataclass(frozen=True)
class LiveAdmission:
    """The verdict from :meth:`LiveGuard.try_acquire`.

    ``admitted`` is True iff the run may proceed (single-flight free AND both caps OK);
    a live reservation + the single-flight flag are then held until :meth:`release`.
    On refusal, ``error_code`` is one of ``live_busy`` / ``live_cap_reached`` with a
    human ``detail`` — the route maps this straight to a 429 JSON body.
    """

    admitted: bool
    error_code: str | None = None     # None on admit
    detail: str | None = None
    task_id: str | None = None        # the budget reservation id (held until release)


class LiveGuard:
    """Single-flight + daily run-count + daily $ cap for live runs (process-global).

    NOT thread-safe by design — FastAPI's async handlers run on one event loop, and the
    acquire/release are synchronous critical sections with no ``await`` inside, so the
    single-flight check-and-set is atomic w.r.t. the loop. (An ``asyncio.Lock`` would add
    nothing here and could only deadlock on the no-await path.)
    """

    def __init__(self) -> None:
        self._active = False                       # single-flight flag
        self._run_day: str = _utc_day()            # the day the count belongs to
        self._run_count = 0                        # live runs started this UTC day
        self._budget = BudgetGuard(caps=BudgetCaps(daily_usd=LIVE_DAILY_CAP_USD))
        self._seq = 0                              # monotonic id source for task_ids

    # ------------------------------------------------------------------

    def is_active(self) -> bool:
        """Whether a live run currently holds the single-flight flag."""
        return self._active

    def _roll_day(self) -> None:
        """Reset the run-count bucket at the UTC day boundary."""
        today = _utc_day()
        if today != self._run_day:
            self._run_day = today
            self._run_count = 0

    def try_acquire(self, *, projected_usd: Decimal | float) -> LiveAdmission:
        """Atomically admit ONE live run, or refuse with a 429 error code.

        Checks, in order: single-flight (``live_busy``), the daily run-count cap and the
        daily $ cap (both ``live_cap_reached``). On admit, sets the single-flight flag,
        increments the day's run count, and reserves ``projected_usd`` against the daily
        budget — all of which :meth:`release` undoes/reconciles. No ``await`` here, so the
        check-and-set is atomic on the event loop.
        """
        self._roll_day()

        if self._active:
            return LiveAdmission(
                admitted=False,
                error_code="live_busy",
                detail="a live run is already in progress",
            )

        if self._run_count >= LIVE_DAILY_RUNS:
            return LiveAdmission(
                admitted=False,
                error_code="live_cap_reached",
                detail=(
                    f"the live demo's daily cap of {LIVE_DAILY_RUNS} runs has been "
                    "reached — try again tomorrow (the cap resets daily)"
                ),
            )

        # Reserve the projected spend against the daily $ cap (authorize).
        self._seq += 1
        task_id = f"live-{self._run_day}-{self._seq}"
        decision = self._budget.check_and_reserve(
            task_id, projected_usd=projected_usd, task_label=LIVE_TASK_LABEL
        )
        if not decision.allowed:
            return LiveAdmission(
                admitted=False,
                error_code="live_cap_reached",
                detail=(
                    f"the live demo's daily spend cap of ${LIVE_DAILY_CAP_USD} has been "
                    "reached — try again tomorrow (the cap resets daily)"
                ),
            )

        # Admit: take the single-flight flag and count the run.
        self._active = True
        self._run_count += 1
        return LiveAdmission(admitted=True, task_id=task_id)

    def release(self, admission: LiveAdmission, *, actual_usd: Decimal | float | None = None) -> None:
        """Release the single-flight flag and reconcile the budget reservation.

        Idempotent and failure-proof: safe to call in a ``finally`` even if the run
        errored or the admission was a refusal (a non-admitted admission has no flag/
        reservation to release). ``actual_usd`` defaults to the projected reservation
        (the guard then just clears it).
        """
        if not admission.admitted:
            return
        # Reconcile the $ reservation (settle); default = leave the projected reserve.
        if admission.task_id is not None:
            if actual_usd is not None:
                self._budget.reconcile(admission.task_id, actual_usd=actual_usd)
            else:
                # Reconcile to the projected amount (a no-op delta) so the reservation
                # is cleared from the ledger but the day's spend still counts it.
                res = self._budget._reservations.get(admission.task_id)  # noqa: SLF001
                if res is not None:
                    self._budget.reconcile(admission.task_id, actual_usd=res.projected_usd)
        self._active = False


_guard: LiveGuard | None = None


def get_live_guard() -> LiveGuard:
    """Return the process-global live guard (built once)."""
    global _guard
    if _guard is None:
        _guard = LiveGuard()
    return _guard


def reset_live_guard() -> None:
    """Drop the singleton so the next ``get_live_guard`` rebuilds it (tests only)."""
    global _guard
    _guard = None
