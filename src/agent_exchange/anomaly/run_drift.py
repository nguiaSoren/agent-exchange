"""Per-run drift orchestration — capture telemetry + evaluate every worker.

This is the thin orchestration seam that sits between a completed marketplace job
and the pure :mod:`.drift` detectors. For each worker that ran on the job it:

1. builds the worker's *current* :class:`~agent_exchange.anomaly.types.JobTelemetry`
   row from the run facts (model, bid, contract length),
2. records that row into the :class:`~agent_exchange.anomaly.telemetry.JsonTelemetryStore`
   (so the row joins the worker's history for the *next* run's baseline),
3. assembles the worker's PER_TASK baseline window (excluding this very job), and
4. runs :func:`agent_exchange.anomaly.drift.evaluate` to get the worker's
   :class:`~agent_exchange.anomaly.types.DriftReport`.

It is **pure except for the store I/O** and the pricing-table read: given the same
inputs (crucially the same injected ``now_ms``) it produces the same reports. It
imports nothing from the server / FastAPI layer so it stays unit-testable.

Live-capture approximations (intentionally coarse — documented, not hidden)
---------------------------------------------------------------------------
Agent Exchange does not thread per-worker LLM token usage through the audit
findings, so the per-worker telemetry row is *estimated*, not metered. The
estimates are deliberately conservative and identical in shape across workers so
they cannot manufacture a spurious drift signal on their own — the demo's
CRITICAL catch comes from the model-swap + bid-price mismatch, which ARE real
per-worker facts (the model each worker ran and the price it bid):

* ``latency_ms`` — a single job-level latency shared across all workers (the
  in-room audit runs the team together; there is no per-worker wall clock). Pass
  ``latency_ms`` in; it is recorded identically on every row. This means latency
  drift is a job-level, not a per-worker, signal here.
* ``llm_call_count`` — assumed ``1`` per worker (one audit pass per specialist).
* ``total_input_tokens`` — estimated from the contract text via
  :func:`agent_exchange.core.pricing.estimate_tokens` (the document the whole
  team reads), so it is the *same* for every worker on the job.
* ``est_cost_usd`` — :func:`agent_exchange.core.pricing.estimate_cost` of that
  one input pass on the worker's actual model (``None`` when the model is
  unpriced — a cost-blind row, which the cost baseline correctly drops).
* ``model_call_counts`` — ``{model: llm_call_count}`` (single-model worker).

The honest read: cost/latency/behavioral drift here are coarse-grained because
the underlying per-worker metering does not exist yet; the model-substitution
signal (model swap + frontier-price-cheap-model) is the load-bearing, fully-real
detector this slice surfaces.
"""

from __future__ import annotations

from .drift import evaluate
from .telemetry import JsonTelemetryStore
from .types import (
    DEFAULT_THRESHOLDS,
    BaselineMode,
    DriftReport,
    DriftThresholds,
    JobTelemetry,
)

# One audit pass per specialist (see module docstring — coarse, documented).
_ASSUMED_LLM_CALLS = 1


def build_worker_telemetry(
    *,
    worker: str,
    model: str,
    kind: str,
    job_id: str,
    now_ms: int,
    contract_text: str,
    latency_ms: int,
) -> JobTelemetry:
    """Build one worker's current :class:`JobTelemetry` row from run facts.

    See the module docstring for the (coarse, documented) estimation rules. The
    token/cost estimate is derived from ``contract_text`` on the worker's
    ``model``; ``est_cost_usd`` is ``None`` for an unpriced model (cost-blind).
    """
    from ..core.pricing import estimate_cost, estimate_tokens

    input_tokens = estimate_tokens(contract_text, model)
    est_cost = estimate_cost(model, contract_text)  # input-only pass; None if unpriced
    return JobTelemetry(
        agent_id=worker,
        job_id=job_id,
        task=kind,
        started_at_ms=now_ms,
        model=model,
        est_cost_usd=est_cost,
        latency_ms=latency_ms,
        llm_call_count=_ASSUMED_LLM_CALLS,
        total_input_tokens=input_tokens,
        tool_call_counts={},
        model_call_counts={model: _ASSUMED_LLM_CALLS},
    )


def evaluate_run_drift(
    store: JsonTelemetryStore,
    *,
    workers: list[str],
    models: dict[str, str],
    bid_prices_atomic: dict[str, int],
    kind: str,
    job_id: str,
    now_ms: int,
    contract_text: str,
    latency_ms: int = 0,
    window_days: int = 90,
    thresholds: DriftThresholds = DEFAULT_THRESHOLDS,
) -> dict[str, DriftReport]:
    """Capture + evaluate drift for every worker that ran on one job.

    For each worker (in the given ``workers`` order): build its current row,
    :meth:`record <agent_exchange.anomaly.telemetry.JsonTelemetryStore.record>`
    it, assemble its PER_TASK baseline (``task=kind``, ``exclude_job_id=job_id``
    so the row just written is never part of its own baseline), and
    :func:`evaluate <agent_exchange.anomaly.drift.evaluate>` it against that
    baseline with its bid price.

    Parameters
    ----------
    store:
        The telemetry store to record into and read baselines from.
    workers:
        Worker ids that ran on this job (the report keys, in order).
    models:
        ``worker -> model id actually run``. A worker missing here is skipped
        (no model to attribute a row to).
    bid_prices_atomic:
        ``worker -> accepted bid in USDC atomic units (6dp)``. Absent → the
        price-mismatch trigger is disabled for that worker (``None``).
    kind:
        The job's task tag (e.g. ``"contract-audit"``) — the PER_TASK filter.
    job_id:
        This run's id; excluded from each worker's own baseline.
    now_ms:
        "Now" in epoch milliseconds, injected for determinism (no clock call
        inside this helper). Stamped on every recorded row.
    contract_text:
        The audited document — drives the token/cost estimate (see module
        docstring; the same text for every worker).
    latency_ms:
        Job-level latency, recorded identically on every worker's row (no
        per-worker wall clock exists; see module docstring).
    window_days:
        Baseline recency window (default 90 days).
    thresholds:
        Drift thresholds; defaults to the AgentScope-verified defaults.

    Returns
    -------
    dict[str, DriftReport]
        One report per worker that had a model. Deterministic given the inputs
        and the store's prior contents.
    """
    reports: dict[str, DriftReport] = {}
    for worker in workers:
        model = models.get(worker)
        if model is None:
            continue
        current = build_worker_telemetry(
            worker=worker,
            model=model,
            kind=kind,
            job_id=job_id,
            now_ms=now_ms,
            contract_text=contract_text,
            latency_ms=latency_ms,
        )
        store.record(current)
        baseline = store.baseline(
            worker,
            task=kind,
            mode=BaselineMode.PER_TASK,
            window_days=window_days,
            now_ms=now_ms,
            exclude_job_id=job_id,
            thresholds=thresholds,
        )
        reports[worker] = evaluate(
            current,
            baseline,
            bid_price_atomic=bid_prices_atomic.get(worker),
            thresholds=thresholds,
        )
    return reports


__all__ = ["build_worker_telemetry", "evaluate_run_drift"]
