"""Process-global demo spend cap for the public ``POST /api/audit`` endpoint.

The audit endpoint runs the REAL workers + the REAL verifier against a document a
judge pastes in. That is real provider spend on every request, so the public endpoint
needs a hard daily ceiling it cannot exceed — otherwise an open demo URL can drain the
AI/ML API budget.

This is a thin singleton wrapper around the project's existing
:class:`agent_exchange.payments.budget_guard.BudgetGuard` (the same reserve → check →
reconcile circuit breaker the marketplace uses). We configure ONLY its daily window cap
(``DEMO_DAILY_CAP_USD``); the guard's day-bucket logic resets the window automatically
at the UTC day boundary, so the cap is "per UTC day" with no extra cron.

Flow per request (mirrors x402 authorize → settle):

    guard = get_demo_guard()
    decision = guard.check_and_reserve(task_id, projected_usd=estimate)   # authorize
    if not decision.allowed:  -> 429 demo_budget_reached
    ...run the audit...
    guard.reconcile(task_id, actual_usd=actual_or_estimate)               # settle

The cap is a module constant so it is trivial to tune for a demo. Money flows through
the guard as ``Decimal`` (6 d.p., USDC atomic resolution) — never a float past the
``BudgetGuard`` boundary.
"""

from __future__ import annotations

from decimal import Decimal

from agent_exchange.payments.budget_guard import BudgetCaps, BudgetGuard

# ---------------------------------------------------------------------------
# The cap. Tune here. $5.00 / UTC day across ALL /api/audit callers combined.
# ---------------------------------------------------------------------------
DEMO_DAILY_CAP_USD: Decimal = Decimal("5.00")

# A stable label for the audit task so all audit reservations share the daily window.
DEMO_TASK_LABEL = "api_audit"

_guard: BudgetGuard | None = None


def get_demo_guard() -> BudgetGuard:
    """Return the process-global demo budget guard (built once, daily cap only).

    The guard is a singleton so every ``/api/audit`` request shares one running daily
    spend counter; restarting the process resets it (acceptable for a demo — there is no
    persistence requirement, only a per-day ceiling while the server is up).
    """
    global _guard
    if _guard is None:
        _guard = BudgetGuard(caps=BudgetCaps(daily_usd=DEMO_DAILY_CAP_USD))
    return _guard


def reset_demo_guard() -> None:
    """Drop the singleton so the next ``get_demo_guard`` rebuilds it (tests only)."""
    global _guard
    _guard = None
