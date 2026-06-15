"""Tests for ``payments.budget_guard.BudgetGuard``.

Covers:
  * Projection math via a fake projector.
  * Per-task cap BLOCK (glob pattern matching, task-session cap).
  * Session-window BLOCK.
  * Daily-window BLOCK (pinned clock crosses day boundary).
  * Rollback on BLOCK — reservation is never left dangling.
  * Passing job under cap settles to actual cost (reconcile).
  * No-guard path in HiringPolicy.select stays unaffected.
  * Budget-guard integration in HiringPolicy.select blocks an over-budget job.

All tests use a fake projector (a simple lambda) and a pinned clock so window
bucket arithmetic is deterministic and independent of wall time.
"""

from __future__ import annotations

import os
import sys
from decimal import Decimal

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from agent_exchange.payments.budget_guard import (
    BudgetCaps,
    BudgetGuard,
    Decision,
    TaskRule,
    _dec,
    _glob_matches,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_D = _dec  # shorthand


def _guard(
    session_usd: str = "0",
    daily_usd: str = "0",
    task_rules: tuple[TaskRule, ...] = (),
    fixed_ts: float = 1_000_000.0,  # a known epoch second (day=11, week=1)
) -> BudgetGuard:
    """Construct a ``BudgetGuard`` with a pinned clock and no injected projector.

    The pinned clock ensures window-bucket arithmetic is reproducible across
    test runs regardless of wall time.
    """
    caps = BudgetCaps(
        session_usd=_D(session_usd),
        daily_usd=_D(daily_usd),
        task_rules=task_rules,
    )
    return BudgetGuard(caps, project_cost=None, now=lambda: fixed_ts)


# ---------------------------------------------------------------------------
# Glob matcher unit tests (port of Rust glob tests)
# ---------------------------------------------------------------------------


def test_glob_exact_match():
    assert _glob_matches("research", "research") is True
    assert _glob_matches("research", "researchy") is False


def test_glob_star_prefix():
    assert _glob_matches("research_*", "research_alpha") is True
    assert _glob_matches("research_*", "research_") is True
    assert _glob_matches("research_*", "rsearch") is False


def test_glob_star_middle():
    assert _glob_matches("a*z", "abz") is True
    assert _glob_matches("a*z", "az") is True
    assert _glob_matches("a*z", "ay") is False


def test_glob_question_mark():
    assert _glob_matches("a?z", "abz") is True
    assert _glob_matches("a?z", "abbz") is False


# ---------------------------------------------------------------------------
# Projection math via fake projector
# ---------------------------------------------------------------------------


def test_projected_cost_from_injected_callable():
    """A fake projector returning a fixed cost is used when projected_usd is None."""
    calls: list[dict] = []

    def fake_projector(**kwargs):
        calls.append(kwargs)
        return 1.5  # $1.50

    caps = BudgetCaps(session_usd=_D("10.00"))
    guard = BudgetGuard(caps, project_cost=fake_projector, now=lambda: 1_000_000.0)

    decision = guard.check_and_reserve("job-1")  # no projected_usd → calls fake
    assert decision.allowed is True
    assert decision.projected_usd == _D("1.500000")
    assert len(calls) == 1
    assert calls[0] == {"task_label": None}


def test_projector_returning_none_is_treated_as_zero_cost():
    """A projector returning None (unknown cost) should not block."""
    caps = BudgetCaps(session_usd=_D("0.01"))  # very tight cap
    guard = BudgetGuard(caps, project_cost=lambda **_: None, now=lambda: 1_000_000.0)

    decision = guard.check_and_reserve("job-unknown")
    assert decision.allowed is True
    assert decision.projected_usd == _D("0")


def test_explicit_projected_usd_overrides_projector():
    """When projected_usd is given, the injected callable is NOT invoked."""
    called = []

    def projector(**kwargs):
        called.append(True)
        return 99.0

    caps = BudgetCaps(session_usd=_D("5.00"))
    guard = BudgetGuard(caps, project_cost=projector, now=lambda: 1_000_000.0)

    decision = guard.check_and_reserve("job-2", projected_usd=Decimal("1.00"))
    assert decision.allowed is True
    assert decision.projected_usd == _D("1.000000")
    assert len(called) == 0  # projector was NOT called


# ---------------------------------------------------------------------------
# Session-window cap tests
# ---------------------------------------------------------------------------


def test_allow_under_session_cap():
    guard = _guard(session_usd="5.00")
    decision = guard.check_and_reserve("job-a", projected_usd=Decimal("2.00"))
    assert decision.allowed is True
    assert decision.breached_window is None


def test_block_at_session_cap():
    guard = _guard(session_usd="5.00")
    # First job: 4.00 — should pass
    d1 = guard.check_and_reserve("job-1", projected_usd=Decimal("4.00"))
    assert d1.allowed is True
    guard.reconcile("job-1", actual_usd=Decimal("4.00"))

    # Second job: 2.00 — would bring session to 6.00, breaching the 5.00 cap
    d2 = guard.check_and_reserve("job-2", projected_usd=Decimal("2.00"))
    assert d2.allowed is False
    assert d2.breached_window == "session"
    assert d2.cap_usd == _D("5.00")


def test_session_cap_unlimited_when_zero():
    guard = _guard(session_usd="0")  # 0 == unlimited
    for i in range(10):
        d = guard.check_and_reserve(f"job-{i}", projected_usd=Decimal("1000.00"))
        assert d.allowed is True
        guard.reconcile(f"job-{i}", actual_usd=Decimal("1000.00"))
    assert guard.session_spend() == _D("10000.000000")


# ---------------------------------------------------------------------------
# Daily-window cap tests (clock pins two different days)
# ---------------------------------------------------------------------------


def test_block_on_daily_cap():
    """Cross the daily cap by pinning the clock to the same day bucket."""
    ts_day1 = 1_000_000.0  # day bucket = 1_000_000 // 86_400 = 11

    caps = BudgetCaps(daily_usd=_D("3.00"), session_usd=_D("0"))
    guard = BudgetGuard(caps, now=lambda: ts_day1)

    d1 = guard.check_and_reserve("job-1", projected_usd=Decimal("2.00"))
    assert d1.allowed is True
    guard.reconcile("job-1", actual_usd=Decimal("2.00"))

    # Second job on the SAME day: 2.00 more → daily total 4.00 > 3.00
    d2 = guard.check_and_reserve("job-2", projected_usd=Decimal("2.00"))
    assert d2.allowed is False
    assert d2.breached_window == "daily"


def test_daily_cap_resets_on_new_day():
    """Daily spend tracked per-bucket: a new day gives a fresh counter."""
    ts_day1 = 1_000_000.0
    ts_day2 = ts_day1 + 86_400  # next UTC day

    caps = BudgetCaps(daily_usd=_D("3.00"), session_usd=_D("0"))

    # Day 1 — spend 2.50
    clock_val = ts_day1
    guard = BudgetGuard(caps, now=lambda: clock_val)
    d1 = guard.check_and_reserve("job-d1", projected_usd=Decimal("2.50"))
    assert d1.allowed is True
    guard.reconcile("job-d1", actual_usd=Decimal("2.50"))

    # Day 2 — a new day bucket; 2.50 fits under the 3.00 daily cap again
    clock_val = ts_day2
    d2 = guard.check_and_reserve("job-d2", projected_usd=Decimal("2.50"))
    assert d2.allowed is True


# ---------------------------------------------------------------------------
# Per-task glob cap tests
# ---------------------------------------------------------------------------


def test_per_task_cap_blocks_matching_glob():
    """A task matching the pattern is blocked when the task-session cap is hit."""
    rule = TaskRule(
        pattern="research_*",
        cap_session_usd=_D("2.00"),
        cap_daily_usd=_D("0"),  # 0 == unlimited
    )
    caps = BudgetCaps(session_usd=_D("100.00"), task_rules=(rule,))
    guard = BudgetGuard(caps, now=lambda: 1_000_000.0)

    # First research job: 1.50 — fits
    d1 = guard.check_and_reserve("job-r1", projected_usd=Decimal("1.50"), task_label="research_alpha")
    assert d1.allowed is True
    guard.reconcile("job-r1", actual_usd=Decimal("1.50"))

    # Second research job: 1.00 — would bring task-session to 2.50, breaching 2.00 cap
    d2 = guard.check_and_reserve("job-r2", projected_usd=Decimal("1.00"), task_label="research_beta")
    assert d2.allowed is False
    assert "task:research_*" in d2.breached_window


def test_per_task_cap_does_not_apply_when_label_mismatches():
    """A job with a non-matching label is not affected by the task rule."""
    rule = TaskRule(
        pattern="research_*",
        cap_session_usd=_D("0.50"),
        cap_daily_usd=_D("0"),
    )
    caps = BudgetCaps(session_usd=_D("100.00"), task_rules=(rule,))
    guard = BudgetGuard(caps, now=lambda: 1_000_000.0)

    # This is a refactor job, not a research job — the tight 0.50 cap doesn't apply
    d = guard.check_and_reserve("job-r", projected_usd=Decimal("5.00"), task_label="refactor_x")
    assert d.allowed is True


def test_task_cap_daily_blocks_within_day():
    """The per-task daily cap is checked in addition to the task-session cap."""
    rule = TaskRule(
        pattern="data_*",
        cap_session_usd=_D("0"),  # unlimited session
        cap_daily_usd=_D("1.00"),
    )
    caps = BudgetCaps(task_rules=(rule,))
    guard = BudgetGuard(caps, now=lambda: 1_000_000.0)

    d1 = guard.check_and_reserve("job-d1", projected_usd=Decimal("0.80"), task_label="data_load")
    assert d1.allowed is True
    guard.reconcile("job-d1", actual_usd=Decimal("0.80"))

    # Second data job on the same day: 0.40 more → 1.20 > 1.00 task-daily cap
    d2 = guard.check_and_reserve("job-d2", projected_usd=Decimal("0.40"), task_label="data_transform")
    assert d2.allowed is False
    assert "task-daily:data_*" in d2.breached_window


# ---------------------------------------------------------------------------
# Rollback-on-BLOCK invariant
# ---------------------------------------------------------------------------


def test_rollback_on_block_leaves_no_dangling_reservation():
    """A BLOCKED check_and_reserve must not inflate the running spend counters."""
    guard = _guard(session_usd="5.00")

    # Allow job-1 and reconcile it (2.00 in session)
    guard.check_and_reserve("job-1", projected_usd=Decimal("2.00"))
    guard.reconcile("job-1", actual_usd=Decimal("2.00"))
    assert guard.session_spend() == _D("2.000000")

    # BLOCK job-2 (2.00 + 4.00 = 6.00 > 5.00)
    d2 = guard.check_and_reserve("job-2", projected_usd=Decimal("4.00"))
    assert d2.allowed is False

    # Session spend must STILL be 2.00 — the blocked projection was rolled back
    assert guard.session_spend() == _D("2.000000"), (
        f"blocked job inflated session spend to {guard.session_spend()}"
    )


def test_reconcile_on_blocked_job_is_noop():
    """Calling reconcile with a task_id that was BLOCKED is safe (no-op)."""
    guard = _guard(session_usd="1.00")
    d = guard.check_and_reserve("job-blocked", projected_usd=Decimal("5.00"))
    assert d.allowed is False

    # reconcile should not raise and should not change the counters
    initial_spend = guard.session_spend()
    guard.reconcile("job-blocked", actual_usd=Decimal("5.00"))
    assert guard.session_spend() == initial_spend


def test_rollback_leaves_correct_state_for_next_allowed_job():
    """After a block-and-rollback, the next job within cap is still allowed."""
    guard = _guard(session_usd="5.00")

    # 4.00 reserved
    d1 = guard.check_and_reserve("job-1", projected_usd=Decimal("4.00"))
    assert d1.allowed is True

    # BLOCK job-2 (4.00 + 3.00 = 7.00 > 5.00)
    d2 = guard.check_and_reserve("job-2", projected_usd=Decimal("3.00"))
    assert d2.allowed is False

    # Session spend = 4.00 (job-1 reservation still in flight)
    assert guard.session_spend() == _D("4.000000")

    # A small third job (0.50) fits under the remaining 1.00 headroom
    d3 = guard.check_and_reserve("job-3", projected_usd=Decimal("0.50"))
    assert d3.allowed is True


# ---------------------------------------------------------------------------
# Passing job settles to actual (reconcile adjusts for under/over-estimate)
# ---------------------------------------------------------------------------


def test_passing_job_under_cap_reconciles_to_actual():
    """Projected 3.00, actual 1.20 — the over-reserve (1.80) is returned."""
    guard = _guard(session_usd="10.00")

    d = guard.check_and_reserve("job-settle", projected_usd=Decimal("3.00"))
    assert d.allowed is True
    assert guard.session_spend() == _D("3.000000")

    # Actual was much cheaper
    guard.reconcile("job-settle", actual_usd=Decimal("1.20"))
    assert guard.session_spend() == _D("1.200000"), (
        f"expected 1.20 after reconcile, got {guard.session_spend()}"
    )


def test_reconcile_overestimate_charges_extra():
    """Projected 1.00, actual 2.00 — the extra 1.00 is added to the counters."""
    guard = _guard(session_usd="100.00")

    d = guard.check_and_reserve("job-over", projected_usd=Decimal("1.00"))
    assert d.allowed is True
    guard.reconcile("job-over", actual_usd=Decimal("2.00"))
    # The extra 1.00 was charged: session = 2.00
    assert guard.session_spend() == _D("2.000000")


def test_multiple_jobs_session_accounting():
    """Three allowed jobs: session spend is the sum of their actual costs."""
    guard = _guard(session_usd="100.00")

    for i, cost in enumerate(["1.00", "2.50", "0.75"]):
        guard.check_and_reserve(f"job-{i}", projected_usd=Decimal(cost))
        guard.reconcile(f"job-{i}", actual_usd=Decimal(cost))

    assert guard.session_spend() == _D("4.250000")


# ---------------------------------------------------------------------------
# HiringPolicy integration — BudgetGuard as an optional kwarg
# ---------------------------------------------------------------------------


def test_hiring_policy_no_guard_is_unchanged():
    """Passing no guard (None) leaves existing hiring behaviour untouched."""
    from agent_exchange.market.hiring import HiringPolicy
    from agent_exchange.market.schema import Bid, Job, ReputationRecord
    from agent_exchange.market.selection import CoverageWithinBudget

    rep = ReputationRecord(worker="x", n_jobs=10, success_rate=0.9)
    job = Job(job_id="acme-1", contract="MSA text", budget_atomic=500_000, title="Audit")
    bids = [
        Bid(worker="a", job_id="acme-1", price_atomic=200_000, relevance_confidence=0.9, reputation=rep),
    ]
    policy = HiringPolicy(CoverageWithinBudget(), seed=1)
    decision = policy.select(job, bids)  # no budget_guard kwarg → no-op
    assert decision.n_hired == 1
    assert decision.budget_block_reason is None


def test_hiring_policy_budget_guard_blocks_over_budget_job():
    """A BudgetGuard that would block the job causes the hiring to be declined.

    The guard has a session cap of $0.001 and a project_cost that returns $0.50,
    so the check will block (projected $0.50 > cap $0.001).  select() no longer
    passes projected_usd directly; the guard uses its injected project_cost.
    """
    from agent_exchange.market.hiring import HiringPolicy
    from agent_exchange.market.schema import Bid, Job, ReputationRecord
    from agent_exchange.market.selection import CoverageWithinBudget

    # Guard with a session cap of $0.001, projector returns $0.50 (way over cap)
    caps = BudgetCaps(session_usd=_D("0.001000"))
    guard = BudgetGuard(caps, project_cost=lambda **_: 0.50, now=lambda: 1_000_000.0)

    rep = ReputationRecord(worker="x", n_jobs=10, success_rate=0.9)
    job = Job(job_id="blocked-job", contract="MSA text", budget_atomic=500_000, title="Audit")
    bids = [
        Bid(worker="a", job_id="blocked-job", price_atomic=200_000, relevance_confidence=0.9, reputation=rep),
    ]

    policy = HiringPolicy(CoverageWithinBudget(), seed=1)
    decision = policy.select(job, bids, budget_guard=guard)

    assert decision.n_hired == 0
    assert decision.over_budget is True
    assert decision.budget_block_reason is not None
    assert "session" in decision.budget_block_reason
    # Worker 'a' should be in declined
    assert "a" in decision.declined


def test_hiring_policy_budget_guard_allows_under_budget_job():
    """A BudgetGuard with a generous cap allows normal hiring to proceed.

    The guard has a $100 session cap and a projector returning $0.10, so the
    check passes and hiring proceeds normally.
    """
    from agent_exchange.market.hiring import HiringPolicy
    from agent_exchange.market.schema import Bid, Job, ReputationRecord
    from agent_exchange.market.selection import CoverageWithinBudget

    caps = BudgetCaps(session_usd=_D("100.00"))
    guard = BudgetGuard(caps, project_cost=lambda **_: 0.10, now=lambda: 1_000_000.0)

    rep = ReputationRecord(worker="x", n_jobs=10, success_rate=0.9)
    job = Job(job_id="ok-job", contract="MSA text", budget_atomic=500_000, title="Audit")
    bids = [
        Bid(worker="a", job_id="ok-job", price_atomic=200_000, relevance_confidence=0.9, reputation=rep),
    ]

    policy = HiringPolicy(CoverageWithinBudget(), seed=1)
    decision = policy.select(job, bids, budget_guard=guard)

    assert decision.n_hired == 1
    assert decision.budget_block_reason is None
    assert decision.over_budget is False


# ---------------------------------------------------------------------------
# budget_guard_for_job factory — real estimate_cost integration
# ---------------------------------------------------------------------------

# A realistic contract sample used by the factory tests.
_SAMPLE_CONTRACT = (
    "This Master Services Agreement ('Agreement') is entered into between Acme Corp "
    "('Client') and the Vendor ('Contractor'). The Contractor agrees to provide software "
    "audit services. Payment terms: Net 30. Limitation of liability: $50,000 per incident. "
    "Governing law: State of Delaware. The Client may terminate this Agreement with 30 days "
    "written notice. The Contractor warrants that all deliverables will meet the agreed "
    "acceptance criteria and will be free from material defects for 90 days post-delivery."
)


def test_budget_guard_for_job_tiny_budget_declines():
    """Factory: a job with a $0.000001 budget is blocked by real token-cost projection."""
    from agent_exchange.market.hiring import HiringPolicy, budget_guard_for_job
    from agent_exchange.market.schema import Bid, Job, ReputationRecord
    from agent_exchange.market.selection import CoverageWithinBudget

    # budget_atomic=1 → $0.000001 — far below any realistic token cost
    job = Job(
        job_id="tiny-budget-job",
        contract=_SAMPLE_CONTRACT,
        budget_atomic=1,
        title="Tiny Budget Audit",
    )
    guard = budget_guard_for_job(
        job,
        worker_model="claude-3-5-haiku",
        verifier_model="claude-3-5-haiku",
        n_workers=2,
        now=lambda: 1_000_000.0,
    )

    rep = ReputationRecord(worker="w", n_jobs=5, success_rate=0.8)
    bids = [
        Bid(worker="w", job_id="tiny-budget-job", price_atomic=1, relevance_confidence=0.9, reputation=rep),
    ]
    policy = HiringPolicy(CoverageWithinBudget(), seed=42)
    decision = policy.select(job, bids, budget_guard=guard)

    assert decision.over_budget is True
    assert decision.n_hired == 0
    assert decision.budget_block_reason is not None


def test_budget_guard_for_job_ample_budget_hires():
    """Factory: a job with a $10.00 budget is well above real token cost; hiring proceeds."""
    from agent_exchange.market.hiring import HiringPolicy, budget_guard_for_job
    from agent_exchange.market.schema import Bid, Job, ReputationRecord
    from agent_exchange.market.selection import CoverageWithinBudget

    # budget_atomic=10_000_000 → $10.00 — far above any realistic token cost for a short contract
    job = Job(
        job_id="ample-budget-job",
        contract=_SAMPLE_CONTRACT,
        budget_atomic=10_000_000,
        title="Ample Budget Audit",
    )
    guard = budget_guard_for_job(
        job,
        worker_model="claude-3-5-haiku",
        verifier_model="claude-3-5-haiku",
        n_workers=2,
        now=lambda: 1_000_000.0,
    )

    rep = ReputationRecord(worker="w", n_jobs=5, success_rate=0.8)
    bids = [
        Bid(worker="w", job_id="ample-budget-job", price_atomic=1_000_000, relevance_confidence=0.9, reputation=rep),
    ]
    policy = HiringPolicy(CoverageWithinBudget(), seed=42)
    decision = policy.select(job, bids, budget_guard=guard)

    assert decision.over_budget is False
    assert decision.n_hired == 1
    assert decision.budget_block_reason is None


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_duplicate_task_id_retried_safely():
    """Submitting the same task_id twice rolls back the first reservation before re-checking."""
    guard = _guard(session_usd="10.00")

    # First check: 5.00 reserved
    d1 = guard.check_and_reserve("job-retry", projected_usd=Decimal("5.00"))
    assert d1.allowed is True
    assert guard.session_spend() == _D("5.000000")

    # Re-check the SAME task_id with a smaller amount: old reservation is rolled back
    # and a fresh one for 2.00 is recorded.
    d2 = guard.check_and_reserve("job-retry", projected_usd=Decimal("2.00"))
    assert d2.allowed is True
    assert guard.session_spend() == _D("2.000000"), (
        f"expected 2.00 after re-reserve, got {guard.session_spend()}"
    )


def test_zero_projected_cost_always_allowed():
    """A zero projected cost never breaches any cap (including a zero-cap limit)."""
    guard = _guard(session_usd="0.00")  # unlimited
    d = guard.check_and_reserve("job-free", projected_usd=Decimal("0"))
    assert d.allowed is True


if __name__ == "__main__":
    import sys

    tests = [(name, fn) for name, fn in sorted(globals().items())
             if name.startswith("test_") and callable(fn)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"  ok  {name}")
        except Exception as exc:
            print(f"  FAIL {name}: {exc}")
            failed += 1
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
