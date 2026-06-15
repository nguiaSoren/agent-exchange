"""Market types — Job, Bid, ReputationRecord + the ReputationStore interface.

The bidding layer's locked contract. A `Job` (a contract to audit + a budget) is
posted to a Band room; candidate specialists each run a cheap relevance-probe and,
if they bid, emit a `Bid` (price + relevance + a reputation snapshot). Hiring (the
next box) consumes the bids.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class Job:
    """A contract-audit job posted to the market."""

    job_id: str
    contract: str
    budget_atomic: int          # max the client authorizes (USDC atomic units)
    title: str = "contract audit"
    room_id: str | None = None  # the Band room hosting this job (set when posted)
    kind: str = "contract-audit"  # job-type routing key (see workers.job_types.JOB_TYPES)

    def preview(self, n_chars: int = 1200) -> str:
        """A short, cheap-to-probe slice of the contract for the relevance probe."""
        return self.contract[:n_chars]


@dataclass(frozen=True, slots=True)
class ReputationRecord:
    """A worker's richer reputation: not a single scalar — success rate, average
    pay earned, job count, and an optional per-specialty breakdown. Starts at a
    neutral prior; the outcome loop updates it via the store."""

    worker: str
    n_jobs: int = 0
    success_rate: float = 0.5        # fraction of jobs with a clean/paid outcome (Bayesian prior 0.5)
    avg_pay_fraction: float = 0.5    # avg fraction of authorized that this worker's findings earned
    per_specialty: dict[str, dict[str, float]] = field(default_factory=dict)  # optional breakdown


@dataclass(frozen=True, slots=True)
class Bid:
    """A worker's bid on a job (only produced when the worker chooses to bid)."""

    worker: str
    job_id: str
    price_atomic: int               # what the worker asks to be paid (USDC atomic)
    relevance_confidence: float     # 0..1 — how relevant the worker judges the job to its specialty
    reputation: ReputationRecord


@runtime_checkable
class ReputationStore(Protocol):
    """Per-worker reputation, persisted. `get` returns a neutral prior for unseen
    workers; `update` folds in one job's outcome."""

    def get(self, worker: str) -> ReputationRecord: ...

    def update(
        self,
        worker: str,
        *,
        success: bool,
        pay_fraction: float,
        specialty: str | None = None,
    ) -> None: ...
