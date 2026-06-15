"""Hiring policy — Thompson-sampled valuation of bids + budget-constrained team selection.

The policy is deliberately split into two halves so each is testable in isolation and
strategies stay pluggable behind the `SelectionStrategy` interface:

1. **Valuation** (`thompson_value` / `score_bids`) — turn each `Bid` into a scalar
   *value*. Value is a Thompson sample: we reconstruct the worker's Beta posterior
   over success from its `ReputationRecord`, draw a quality estimate `theta`, and scale
   it by the bid's self-judged relevance. Sampling (rather than using the posterior
   mean) is what gives the market its explore/exploit behaviour — an unproven worker
   has a *wide* posterior and so occasionally samples high and gets a chance, while a
   worker with a long clean record has a *tight, high* posterior and is reliably
   ranked up.
2. **Selection** (`CoverageWithinBudget`, and later `KnapsackStrategy`) — given the
   value-scored bids and a budget, pick the team. The market posts one bid per
   specialty, so "coverage" is simply the set of specialty-areas the hired bids span;
   covering greedily by value within budget maximises covered value per dollar in the
   common case.

Pure module: stdlib `random` only, no Band/LLM/network. Every function is deterministic
given the `random.Random` it is handed — pass a seeded RNG for reproducible hiring.
"""

from __future__ import annotations

import random

from .hiring_types import Hire, ScoredBid
from .schema import Bid, ReputationRecord

# Beta parameters are clamped to this floor so `random.betavariate` never sees a
# non-positive shape (it requires alpha, beta > 0); 1e-6 keeps the posterior
# effectively unchanged while staying safely positive.
_BETA_FLOOR = 1e-6


def thompson_value(
    reputation: ReputationRecord,
    relevance: float,
    rng: random.Random,
    *,
    specialty: str | None = None,
) -> float:
    """Draw a Thompson sample of a worker's expected quality on a bid.

    Contextual by specialty: when a ``specialty`` is given and the worker has a
    track record in it, the posterior is reconstructed from that specialty's own
    counts, so e.g. a worker's TAX history drives its value on a tax job rather
    than its blended global rate. With no specialty — or a specialty the worker
    has never been seen in — it falls back to the GLOBAL posterior unchanged, so a
    fresh / unproven specialty still explores via the neutral global prior.

    The reputation store persists success as a smoothed rate
    ``success_rate = (1 + n_success) / (2 + n_jobs)`` (a Beta(1, 1) / Laplace prior).
    We invert that smoothing to recover the underlying Beta posterior's shape
    parameters, then sample from it::

        alpha = success_rate * (n_jobs + 2)         # ≈ 1 + n_success
        beta  = (n_jobs + 2) - alpha                # ≈ 1 + n_failure

    For the contextual path the SAME inversion is applied to the per-specialty
    posterior carried in ``reputation.per_specialty[specialty]`` (the store returns
    each specialty's smoothed ``success_rate`` + ``n_jobs``)::

        alpha = spec_success_rate * (n_jobs + 2)
        beta  = (n_jobs + 2) - alpha

    Both shapes are clamped to ``>= 1e-6`` so `betavariate` always gets positive
    shapes. The drawn ``theta`` (the sampled success probability) is then scaled by
    the bid's relevance, clamped to ``[0, 1]``, to give the value the policy ranks
    on.

    With the neutral prior (``n_jobs=0``, ``success_rate=0.5``) this is Beta(1, 1) —
    a flat posterior, i.e. maximum exploration of an unproven worker. As a worker
    accumulates successful jobs the posterior tightens around a high mean, i.e.
    exploitation. The same explore→exploit shape holds per-specialty.

    Args:
        reputation: The worker's reputation snapshot carried on its bid.
        relevance: The bid's self-judged relevance to the job, in ``[0, 1]``.
        rng: Source of randomness; the result is deterministic given this RNG.
        specialty: Optional specialty context to score against. When the worker has
            ``per_specialty[specialty]`` with ``n_jobs > 0`` the posterior is drawn
            from that specialty's counts; otherwise (no specialty, or an unseen
            specialty) the global posterior is used so a fresh specialty still
            explores via the neutral global prior.

    Returns:
        ``theta * clamp(relevance, 0, 1)`` — a non-negative sampled value in ``[0, 1]``.
    """
    spec = reputation.per_specialty.get(specialty) if specialty is not None else None
    if spec is not None and spec.get("n_jobs", 0) > 0:
        # Contextual path: this specialty's own DERIVED posterior. The store returns
        # per_specialty as {success_rate, avg_pay_fraction, n_jobs} (smoothing already
        # applied), so use success_rate + n_jobs directly, mirroring the global path.
        n = int(spec["n_jobs"])
        pseudo_total = n + 2
        rate = float(spec["success_rate"])
    else:
        # Fallback: an unseen specialty (or no specialty) explores via the global
        # posterior — identical to the original, specialty-unaware behavior.
        pseudo_total = reputation.n_jobs + 2
        rate = reputation.success_rate

    alpha = max(_BETA_FLOOR, rate * pseudo_total)
    beta = max(_BETA_FLOOR, pseudo_total - alpha)
    theta = rng.betavariate(alpha, beta)
    relevance_clamped = max(0.0, min(1.0, relevance))
    return theta * relevance_clamped


def score_bids(bids: list[Bid], rng: random.Random) -> list[ScoredBid]:
    """Value every bid via a Thompson sample of its worker's reputation × relevance.

    Scoring is **contextual**: each bid is valued against its worker's track record
    *in its own specialty* (``bid.worker`` names the specialty) when one exists,
    falling back to the worker's global posterior otherwise.

    Args:
        bids: The bids to value.
        rng: Source of randomness, threaded into each `thompson_value` draw; the
            whole list is deterministic given this RNG (bids are sampled in order).

    Returns:
        One `ScoredBid` per input bid, in the same order, each carrying its sampled
        `value`.
    """
    return [
        ScoredBid(
            bid=bid,
            value=thompson_value(
                bid.reputation,
                bid.relevance_confidence,
                rng,
                specialty=bid.worker,
            ),
        )
        for bid in bids
    ]


class CoverageWithinBudget:
    """Greedy "cover the most value per dollar" selection strategy.

    Sort the value-scored bids by `value` descending and hire greedily while the
    cumulative price stays within budget. Because the market posts one bid per
    specialty, hiring high-value bids first greedily covers the most valuable
    specialty-areas the budget can afford.

    Soft-cap fallback: if *nothing* fits — even the single highest-value bid's price
    exceeds the whole budget — we hire that one best bid anyway and flag
    ``over_budget=True``, so a demo job always yields a non-empty team rather than an
    empty one. This is the only case in which the returned spend can exceed budget.
    """

    name = "coverage_within_budget"

    def select(
        self,
        scored: list[ScoredBid],
        budget_atomic: int,
    ) -> tuple[list[Hire], list[str], bool]:
        """Pick a team from value-scored bids under a budget.

        Args:
            scored: Value-scored bids (any order; sorted internally by value desc).
            budget_atomic: Spend cap in USDC atomic units.

        Returns:
            ``(hired, declined, over_budget)`` where ``declined`` is the worker names
            of every bid not hired and ``over_budget`` flags the soft-cap fallback.
        """
        ranked = sorted(scored, key=lambda s: s.value, reverse=True)

        hired: list[Hire] = []
        declined: list[str] = []
        spent = 0
        for s in ranked:
            price = s.bid.price_atomic
            if spent + price <= budget_atomic:
                hired.append(
                    Hire(
                        worker=s.bid.worker,
                        price_atomic=price,
                        value=s.value,
                        relevance=s.bid.relevance_confidence,
                    )
                )
                spent += price
            else:
                declined.append(s.bid.worker)

        # Soft-cap fallback: nothing fit, but a demo job must still yield a team.
        over_budget = False
        if not hired and ranked:
            best = ranked[0]
            hired.append(
                Hire(
                    worker=best.bid.worker,
                    price_atomic=best.bid.price_atomic,
                    value=best.value,
                    relevance=best.bid.relevance_confidence,
                )
            )
            declined = [s.bid.worker for s in ranked[1:]]
            over_budget = True

        return hired, declined, over_budget


class KnapsackStrategy:
    """Budget-constrained value-maximising selection — an owed follow-up (STUB).

    Where `CoverageWithinBudget` is a greedy heuristic, this strategy solves the
    selection *optimally* as a 0/1 knapsack:

        choose a subset S of the scored bids
        maximising   Σ_{b in S} value(b)
        subject to   Σ_{b in S} price_atomic(b)  <=  budget_atomic
        each bid taken at most once (0/1, not unbounded — a worker is hired or not).

    The standard solution is dynamic programming over (bid_index, budget_remaining),
    table size O(n · budget_atomic); since `budget_atomic` is in atomic USDC units this
    is pseudo-polynomial and may want a scaling/quantisation step before it is
    practical at fine granularity. The soft-cap fallback (hire the single best bid when
    nothing fits) and the `(hired, declined, over_budget)` return contract carry over
    unchanged from `CoverageWithinBudget`, so this can be dropped in behind the same
    `SelectionStrategy` interface with no caller change.

    Not implemented yet — the seam is locked so the policy can swap strategies later.
    """

    name = "knapsack"

    def select(
        self,
        scored: list[ScoredBid],
        budget_atomic: int,
    ) -> tuple[list[Hire], list[str], bool]:
        """Raise — see the class docstring for the owed 0/1-knapsack design."""
        raise NotImplementedError(
            "KnapsackStrategy is an owed follow-up — see docstring"
        )
