"""AuditPool — concurrent fan-out of audit specialists over a contract.

A pool takes a list of :class:`~agent_exchange.workers.finding.Specialist` workers and
runs them **concurrently** against a single contract, then aggregates every worker's
findings into one flat, deterministic list.

Design constraints (see module-level docstring of ``finding.py`` for the locked
``Finding`` / ``Specialist`` contract this builds against):

* **Bounded fan-out** — concurrency is capped by an ``asyncio.Semaphore`` so a large
  roster of specialists cannot cascade-429 the underlying providers (an
  unbounded ``gather`` over N network-backed workers will hammer rate limits).
* **Fail-safe per specialist** — a worker that raises (network error, JSON parse
  failure, anything) is contained: it contributes zero findings, the pool keeps
  running, and the error is *recorded* (never silently swallowed). Recorded errors
  are exposed on :attr:`AuditPool.errors` and emitted at ``WARNING`` level.
* **Deterministic aggregation** — though work runs concurrently, the returned list is
  reproducible: specialists are ordered by ``.name``, and each specialist's findings
  preserve their original order.
"""

from __future__ import annotations

import asyncio
import logging

from agent_exchange.workers.finding import Finding, Specialist

__all__ = ["AuditPool"]

_log = logging.getLogger(__name__)


class AuditPool:
    """Fan a roster of :class:`Specialist` workers over a contract, in parallel.

    The pool runs all specialists concurrently (bounded by ``max_concurrency``) and
    aggregates their findings into a single deterministic list. Specialist failures are
    isolated: a raising worker yields no findings and is recorded on :attr:`errors`
    rather than crashing the run.

    Attributes:
        specialists: The roster of workers this pool fans out over.
        max_concurrency: Maximum number of specialists allowed to run at once.
        errors: ``(worker_name, error_str)`` tuples recorded during the most recent
            :meth:`run` call. Reset at the start of every :meth:`run`.
    """

    def __init__(self, specialists: list[Specialist], *, max_concurrency: int = 6) -> None:
        """Initialise the pool.

        Args:
            specialists: The specialist workers to fan out over a contract. May be empty
                (in which case :meth:`run` is a no-op returning ``[]``).
            max_concurrency: Upper bound on concurrently-running specialists. Must be a
                positive integer; this caps provider fan-out to avoid cascade-429s.

        Raises:
            ValueError: If ``max_concurrency`` is not a positive integer.
        """
        if max_concurrency < 1:
            raise ValueError(f"max_concurrency must be >= 1, got {max_concurrency!r}")
        self.specialists: list[Specialist] = list(specialists)
        self.max_concurrency: int = max_concurrency
        self.errors: list[tuple[str, str]] = []

    async def _collect(
        self, specialist: Specialist, contract: str, sem: asyncio.Semaphore
    ) -> list[Finding]:
        """Run one specialist under the concurrency gate, containing any failure.

        Args:
            specialist: The worker to run.
            contract: The contract text passed to ``specialist.findings``.
            sem: The shared semaphore bounding overall fan-out.

        Returns:
            The specialist's findings, or ``[]`` if it raised (the error is recorded on
            :attr:`errors` and logged at ``WARNING``).
        """
        async with sem:
            try:
                findings = await specialist.findings(contract)
                # Defensive: a well-behaved Specialist returns a list, but a buggy one
                # might return None; normalise so aggregation never trips on it.
                return list(findings) if findings else []
            except Exception as exc:  # noqa: BLE001 — intentional: contain + record, never swallow.
                name = getattr(specialist, "name", repr(specialist))
                self.errors.append((name, f"{type(exc).__name__}: {exc}"))
                _log.warning(
                    "specialist %r failed during audit; treating as 0 findings: %s",
                    name,
                    exc,
                    exc_info=True,
                )
                return []

    async def run(self, contract: str) -> list[Finding]:
        """Fan all specialists over ``contract`` concurrently and aggregate findings.

        Specialists run in parallel, bounded by ``max_concurrency``. The returned list is
        deterministic: specialists are ordered by ``.name`` (ties broken by their original
        roster position for stability), and within each specialist the findings preserve
        their emitted order. Failing specialists contribute nothing and are recorded on
        :attr:`errors`.

        Args:
            contract: The contract text to audit.

        Returns:
            The flattened findings from all specialists, in deterministic order.
        """
        self.errors = []  # reset per run, before any work starts
        if not self.specialists:
            return []

        sem = asyncio.Semaphore(self.max_concurrency)

        # Pair each specialist with its original index so equal-named specialists keep a
        # stable, reproducible relative order after sorting.
        indexed = list(enumerate(self.specialists))

        # Launch concurrently; results stay positionally aligned with ``indexed``.
        results = await asyncio.gather(
            *(self._collect(spec, contract, sem) for _, spec in indexed)
        )

        # Deterministic assembly: sort by (name, original index), then flatten in order.
        ordered = sorted(
            zip(indexed, results),
            key=lambda pair: (getattr(pair[0][1], "name", ""), pair[0][0]),
        )
        aggregated: list[Finding] = []
        for _, findings in ordered:
            aggregated.extend(findings)
        return aggregated
