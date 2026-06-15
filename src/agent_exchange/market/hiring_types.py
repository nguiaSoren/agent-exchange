"""Hiring types + the SelectionStrategy interface — the hiring-policy contract.

Selection is split from the policy so strategies are pluggable: `CoverageWithinBudget`
ships now; `KnapsackStrategy` (budget-constrained value maximization) is an owed
follow-up that implements the SAME `SelectionStrategy` interface. The policy itself
(Thompson sampling over reputation + relevance) is strategy-agnostic.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from .schema import Bid


@dataclass(frozen=True, slots=True)
class ScoredBid:
    """A bid plus its Thompson value sample (expected quality drawn from the
    worker's reputation posterior × the bid's relevance)."""

    bid: Bid
    value: float  # the sampled value the policy ranks/selects on


@dataclass(frozen=True, slots=True)
class Hire:
    """One hired worker."""

    worker: str
    price_atomic: int
    value: float            # the Thompson value it was hired on
    relevance: float


@dataclass(frozen=True, slots=True)
class HiringDecision:
    """The outcome of a hiring round."""

    hired: tuple[Hire, ...]
    declined: tuple[str, ...]          # worker names not hired
    total_price_atomic: int
    budget_atomic: int
    over_budget: bool                  # True if the soft budget cap was exceeded (fallback fired)
    strategy: str
    budget_block_reason: str | None = None  # set when a BudgetGuard blocked the job pre-hire

    @property
    def n_hired(self) -> int:
        return len(self.hired)

    @property
    def hired_workers(self) -> tuple[str, ...]:
        return tuple(h.worker for h in self.hired)


@runtime_checkable
class SelectionStrategy(Protocol):
    """Picks a team from value-scored bids under a budget.

    Returns (hired, declined_worker_names, over_budget). `over_budget` signals the
    soft-cap fallback fired (e.g. the best single bid exceeded the budget and was
    hired anyway so a demo job always produces a team)."""

    name: str

    def select(
        self,
        scored: list[ScoredBid],
        budget_atomic: int,
    ) -> tuple[list[Hire], list[str], bool]: ...
