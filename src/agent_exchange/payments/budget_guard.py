"""Budget-guard circuit breaker — decline an over-budget job BEFORE burning tokens.

This module ports the three-step ``BudgetGuard`` state machine from
``agentscope-proxy/src/budget_guard.rs`` into Python. It is the *pre-spend*
enforcement layer: a job is BLOCKED before any LLM call is made, not after.

### Three-step state machine (mirrors §15.1 of the AgentScope spec)

1. **Project** — before accepting a job, project its cost with an injected
   ``project_cost`` callable (dependency injection — this module never imports
   core/pricing directly; the orchestrator wires the real estimator in).
2. **Check + reserve** — compare the projected cost against every active window
   cap (session / daily / per-task glob).  If any cap is breached → BLOCK and
   return a ``Decision`` with ``allowed=False``; no reservation is recorded.
   If all caps are OK → ALLOW and record a *reservation* (the projected cost is
   held against every window counter so the next call sees it).
3. **Reconcile** — once the job finishes, replace the reservation with the
   actual cost (``reconcile``).  If actual < projected, the over-reserve is
   returned; if actual > projected (an underestimate), the overage is charged.
   A job that was BLOCKED in step 2 had no reservation → ``reconcile`` is a
   safe no-op.

### Correspondence to x402 authorize → settle

This mirrors the x402 / Permit2 ``upto`` scheme used in
``payments/settlement.py``:

  * ``reserve``   ≈ x402 ``authorize``  — commit an upper bound up front.
  * ``reconcile`` ≈ x402 ``settle``     — settle the actual (≤ reserved) and
                                          roll back the unused remainder.
  * A BLOCKED job never produces a reservation, just as a payment authorization
    that fails ``verify`` never proceeds to ``settle``.

### Money discipline

All spent amounts are tracked as **Decimal** values with six decimal places
(matching USDC's 6-decimal atomic representation).  Callers and the
``project_cost`` injector may pass ``float`` or ``Decimal``; the guard converts
at the boundary.  No arithmetic is done on raw floats internally (no drift).

### Injectable seams

* ``project_cost: Callable[..., float | None]`` — injected cost estimator;
  returning ``None`` means "I cannot estimate" (treated as 0 by the guard,
  i.e. the guard does not block on unknown cost).
* ``now: Callable[[], float]`` — injected clock (``time.time``-shaped);
  defaults to ``time.time``.  Tests pin this to control window buckets.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP
from typing import Callable

# ---------------------------------------------------------------------------
# Money helpers
# ---------------------------------------------------------------------------

_SIX = Decimal("0.000001")  # six decimal places — matches USDC atomic resolution


def _dec(value: float | Decimal | int) -> Decimal:
    """Convert any numeric value to a Decimal, quantised to 6 d.p."""
    if isinstance(value, Decimal):
        return value.quantize(_SIX, rounding=ROUND_HALF_UP)
    return Decimal(str(value)).quantize(_SIX, rounding=ROUND_HALF_UP)


_ZERO = _dec(0)

# ---------------------------------------------------------------------------
# Time-window bucket helpers (mirror budget_guard.rs ``bucket`` module)
# ---------------------------------------------------------------------------

_SECS_PER_DAY: int = 86_400
_SECS_PER_WEEK: int = 604_800


def _day_bucket(ts: float) -> int:
    """UTC day index since unix epoch (same as Rust ``bucket::day``)."""
    return int(ts) // _SECS_PER_DAY


def _week_bucket(ts: float) -> int:
    """Rolling 7-day bucket since unix epoch (same as Rust ``bucket::week_rolling``)."""
    return int(ts) // _SECS_PER_WEEK


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TaskRule:
    """A per-task-pattern budget cap.  ``pattern`` is a simple glob (``*`` / ``?``)
    matched against the ``task_label`` supplied at check time."""

    pattern: str
    cap_session_usd: Decimal  # 0 == unlimited
    cap_daily_usd: Decimal    # 0 == unlimited


@dataclass(frozen=True, slots=True)
class BudgetCaps:
    """Global + per-task budget caps.

    A cap of ``Decimal('0')`` means unlimited (the same convention as the Rust
    source: ``0.0 means unlimited``).
    """

    session_usd: Decimal = _ZERO       # 0 == unlimited
    daily_usd: Decimal = _ZERO         # 0 == unlimited
    task_rules: tuple[TaskRule, ...] = ()


@dataclass(frozen=True, slots=True)
class Decision:
    """The verdict from ``check_and_reserve``.

    ``allowed`` is False when any cap was breached.  ``breached_window`` names
    the first breached window (e.g. ``"session"``, ``"daily"``,
    ``"task:research_*"``).  ``projected_usd`` echoes the projected cost that
    was used for the check.
    """

    allowed: bool
    projected_usd: Decimal
    breached_window: str | None = None   # None on ALLOW
    cap_usd: Decimal = _ZERO             # the cap that was breached (0 = unknown)
    spend_usd: Decimal = _ZERO           # the running spend at breach time


# ---------------------------------------------------------------------------
# Internal per-task-pattern glob matcher (mirrors budget_guard.rs glob_inner)
# ---------------------------------------------------------------------------


def _glob_matches(pattern: str, label: str) -> bool:
    """Minimal glob: ``*`` matches any sequence; ``?`` matches one character.

    Ported verbatim from the Rust ``glob_inner`` backtracking implementation.
    """
    p_bytes = pattern.encode()
    t_bytes = label.encode()
    p = t = 0
    star_p: int | None = None
    star_t: int = 0

    while t < len(t_bytes):
        if p < len(p_bytes) and (p_bytes[p] == t_bytes[t] or p_bytes[p] == ord("?")):
            p += 1
            t += 1
        elif p < len(p_bytes) and p_bytes[p] == ord("*"):
            star_p = p
            star_t = t
            p += 1
        elif star_p is not None:
            p = star_p + 1
            star_t += 1
            t = star_t
        else:
            return False

    while p < len(p_bytes) and p_bytes[p] == ord("*"):
        p += 1
    return p == len(p_bytes)


# ---------------------------------------------------------------------------
# In-flight reservation record
# ---------------------------------------------------------------------------


@dataclass
class _Reservation:
    """One outstanding cost reservation (for one task_id)."""

    projected_usd: Decimal
    ts: float          # wall-clock second at reserve time (for window-bucket attribution)
    task_pattern: str | None  # matched task-rule pattern, or None


# ---------------------------------------------------------------------------
# BudgetGuard
# ---------------------------------------------------------------------------


class BudgetGuard:
    """Pre-spend circuit breaker with multi-window caps and a reservation ledger.

    Instantiate with ``BudgetCaps`` and an injected ``project_cost`` callable.
    The guard is intentionally decoupled from any LLM/pricing import — all
    cost estimation is done by the injected callable.

    Usage::

        guard = BudgetGuard(
            caps=BudgetCaps(session_usd=Decimal("5.00")),
            project_cost=my_estimator,
        )

        decision = guard.check_and_reserve("job-42", projected_usd=Decimal("1.50"))
        if not decision.allowed:
            raise BudgetExceeded(decision)
        ...
        guard.reconcile("job-42", actual_usd=Decimal("1.20"))

    The guard is NOT thread-safe.  Wrap in a lock if shared across threads.
    """

    def __init__(
        self,
        caps: BudgetCaps,
        project_cost: Callable[..., "float | Decimal | None"] | None = None,
        *,
        now: Callable[[], float] | None = None,
    ) -> None:
        """
        Args:
            caps: The multi-window budget caps.
            project_cost: Injected cost estimator; ``None`` means no estimator is
                wired — callers must pass ``projected_usd`` directly to
                ``check_and_reserve``.  Returning ``None`` from the callable means
                "cannot estimate" (treated as 0 → no block).
            now: Injected clock (``float`` seconds since epoch, like
                ``time.time``). Defaults to ``time.time``.  Tests pin this to
                control day/week bucket boundaries.
        """
        self.caps = caps
        self.project_cost = project_cost
        self._now: Callable[[], float] = now if now is not None else time.time

        # Running spend accumulators (Decimal, 6 d.p.).
        self._session_spend: Decimal = _ZERO
        # {day_bucket -> spend}
        self._daily_spend: dict[int, Decimal] = {}
        # {task_pattern -> session spend}
        self._task_session_spend: dict[str, Decimal] = {}
        # {(task_pattern, day_bucket) -> spend}
        self._task_daily_spend: dict[tuple[str, int], Decimal] = {}

        # Outstanding reservations: {task_id -> _Reservation}
        self._reservations: dict[str, _Reservation] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def check_and_reserve(
        self,
        task_id: str,
        projected_usd: "float | Decimal | None" = None,
        *,
        task_label: str | None = None,
    ) -> Decision:
        """Project cost → check every window cap → reserve if OK, else BLOCK.

        Step 1 (project): if ``projected_usd`` is None and a ``project_cost``
        callable was injected, the callable is invoked with the ``task_label``
        keyword argument.  If the callable also returns None (unknown cost), the
        guard allows the call (unknown cost is not blocked).

        Step 2 (check + reserve):
          * Provisionally add the projected cost to all running counters.
          * If any cap is breached → ROLL BACK the provisional add; return
            ``Decision(allowed=False, ...)``.  No reservation is recorded.
          * If all caps are OK → leave the counters as-is (the reservation
            IS the counter delta); record the reservation so ``reconcile`` can
            later swap the estimate for the actual.

        Duplicate ``task_id``: if ``task_id`` already has an outstanding
        reservation, the old reservation is reconciled to 0 before the new one
        is processed (prevents double-booking on retry).

        Args:
            task_id: Stable identifier for this task (used to pair with
                ``reconcile``).
            projected_usd: Override projected cost.  When ``None`` and
                ``project_cost`` was injected, the callable is invoked.
            task_label: Optional label matched against ``TaskRule.pattern``
                globs.  A matching rule's cap is checked in addition to the
                global caps.

        Returns:
            A ``Decision`` with ``allowed=True`` and a live reservation, or
            ``allowed=False`` and no reservation.
        """
        ts = self._now()

        # Resolve projected cost.
        if projected_usd is None:
            if self.project_cost is not None:
                raw = self.project_cost(task_label=task_label)
                proj = _dec(raw) if raw is not None else _ZERO
            else:
                proj = _ZERO
        else:
            proj = _dec(projected_usd)

        # If a prior reservation exists for this task_id, roll it back first
        # (safe retry / idempotent re-check).
        if task_id in self._reservations:
            self._rollback_reservation(task_id)

        # Match task rules.
        task_rule = self._match_task_rule(task_label)
        task_pattern = task_rule.pattern if task_rule is not None else None

        # Provisionally add proj to all counters.
        self._add(proj, ts, task_pattern)

        # Check every active window cap.
        breached_window, cap_at_breach, spend_at_breach = self._check_caps(
            proj, ts, task_rule
        )

        if breached_window is not None:
            # BLOCK — roll back the provisional add; no reservation recorded.
            self._add(-proj, ts, task_pattern)
            return Decision(
                allowed=False,
                projected_usd=proj,
                breached_window=breached_window,
                cap_usd=cap_at_breach,
                spend_usd=spend_at_breach,
            )

        # ALLOW — leave the counter delta in place; record the reservation.
        self._reservations[task_id] = _Reservation(
            projected_usd=proj,
            ts=ts,
            task_pattern=task_pattern,
        )
        return Decision(allowed=True, projected_usd=proj)

    def reconcile(self, task_id: str, actual_usd: "float | Decimal") -> None:
        """Replace the reservation with the actual cost.

        If ``actual_usd < projected_usd``, the over-reserve is returned to the
        counters.  If ``actual_usd > projected_usd`` (underestimate), the extra
        is charged.

        If ``task_id`` was BLOCKED (no reservation was recorded), this is a safe
        no-op — a blocked job leaves no dangling reservation.

        Args:
            task_id: Must match the ``task_id`` passed to ``check_and_reserve``.
            actual_usd: The real cost of the completed task.
        """
        res = self._reservations.pop(task_id, None)
        if res is None:
            # No reservation → either the job was BLOCKED (correct) or the
            # task_id was never reserved (caller error, silently ignored).
            return

        actual = _dec(actual_usd)
        delta = actual - res.projected_usd  # positive = underestimate, negative = over-reserve
        if delta != _ZERO:
            self._add(delta, res.ts, res.task_pattern)

    # ------------------------------------------------------------------
    # Spend query helpers (used in tests to assert internal state)
    # ------------------------------------------------------------------

    def session_spend(self) -> Decimal:
        """Current session spend (includes all active reservations)."""
        return self._session_spend

    def daily_spend(self, ts: float | None = None) -> Decimal:
        """Current day-bucket spend for the given timestamp (default: now)."""
        bucket = _day_bucket(ts if ts is not None else self._now())
        return self._daily_spend.get(bucket, _ZERO)

    def task_session_spend(self, pattern: str) -> Decimal:
        """Current session spend for a specific task-rule pattern."""
        return self._task_session_spend.get(pattern, _ZERO)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _add(self, amount: Decimal, ts: float, task_pattern: str | None) -> None:
        """Add ``amount`` to all relevant window counters (negative = rollback)."""
        self._session_spend += amount
        day = _day_bucket(ts)
        self._daily_spend[day] = self._daily_spend.get(day, _ZERO) + amount
        if task_pattern is not None:
            self._task_session_spend[task_pattern] = (
                self._task_session_spend.get(task_pattern, _ZERO) + amount
            )
            key = (task_pattern, day)
            self._task_daily_spend[key] = self._task_daily_spend.get(key, _ZERO) + amount

    def _rollback_reservation(self, task_id: str) -> None:
        """Remove and roll back an existing reservation (used on retry)."""
        res = self._reservations.pop(task_id, None)
        if res is None:
            return
        self._add(-res.projected_usd, res.ts, res.task_pattern)

    def _match_task_rule(self, task_label: str | None) -> TaskRule | None:
        """Return the first ``TaskRule`` whose pattern matches ``task_label``.

        Returns ``None`` if no label is given or no rule matches (first-match,
        mirrors Rust's ``match_task_rule`` determinism convention).
        """
        if task_label is None:
            return None
        for rule in self.caps.task_rules:
            if _glob_matches(rule.pattern, task_label):
                return rule
        return None

    def _current_session(self) -> Decimal:
        return self._session_spend

    def _current_daily(self, ts: float) -> Decimal:
        return self._daily_spend.get(_day_bucket(ts), _ZERO)

    def _current_task_session(self, pattern: str) -> Decimal:
        return self._task_session_spend.get(pattern, _ZERO)

    def _current_task_daily(self, pattern: str, ts: float) -> Decimal:
        return self._task_daily_spend.get((pattern, _day_bucket(ts)), _ZERO)

    def _check_caps(
        self,
        projected: Decimal,
        ts: float,
        task_rule: TaskRule | None,
    ) -> tuple[str | None, Decimal, Decimal]:
        """Check every active window cap after the provisional add.

        Returns ``(breached_window, cap, spend)`` — window name is None if no cap
        is breached (ALLOW).  The first breach found wins (session > daily > task-
        session > task-daily ordering, matching the Rust ``active_limits`` order).
        """
        checks: list[tuple[str, Decimal, Decimal]] = [
            ("session", self.caps.session_usd, self._current_session()),
            ("daily", self.caps.daily_usd, self._current_daily(ts)),
        ]
        if task_rule is not None:
            pat = task_rule.pattern
            checks.append(
                (f"task:{pat}", task_rule.cap_session_usd, self._current_task_session(pat))
            )
            checks.append(
                (
                    f"task-daily:{pat}",
                    task_rule.cap_daily_usd,
                    self._current_task_daily(pat, ts),
                )
            )

        for window, cap, spend in checks:
            if cap <= _ZERO:
                continue  # 0 == unlimited
            if spend > cap:
                return window, cap, spend

        return None, _ZERO, _ZERO
