"""JSON-backed per-agent telemetry store for the anomaly / drift layer.

Implements :class:`JsonTelemetryStore`, the producer side of the
:mod:`.types` schema seam. It records one immutable
:class:`~agent_exchange.anomaly.types.JobTelemetry` row per ``(agent, job)`` and
assembles the :class:`~agent_exchange.anomaly.types.BaselineWindow` a current row
is judged against (recency-filtered, optionally task-filtered, tiered by sample
size). The detectors in :mod:`.drift` consume those windows; this module never
performs detection.

Port note (vs AgentScope ``agentscope-anomaly``)
------------------------------------------------
AgentScope keyed baselines off a *span DB per run* — ``baseline_window.rs``
walked ``~/.agentscope/runs/run_*.db``, opened each read-only, and aggregated one
``BaselineSample`` per run. Agent Exchange has no span DB: the unit of
observation is a job, so a row is produced directly at job completion and stored
as a per-``(agent, job)`` dict. This store therefore replaces the per-DB walk
with a single JSON file keyed by ``agent_id`` → list of row dicts, but ports the
*logic* of ``load_baseline_window`` (recency filter, current-job exclusion,
per-task vs global split, count bookkeeping) and ``resolve_baseline_mode``
(``shared_rules.rs``) verbatim. See :meth:`JsonTelemetryStore.baseline`.

On-disk schema (a single JSON object keyed by agent id)::

    {
      "<agent_id>": [
        {
          "agent_id": str, "job_id": str, "task": str | null,
          "started_at_ms": int, "model": str, "est_cost_usd": float | null,
          "latency_ms": int, "llm_call_count": int, "total_input_tokens": int,
          "tool_call_counts": {str: int}, "model_call_counts": {str: int}
        },
        ...
      ],
      ...
    }

Writes are atomic (temp file in the same dir + ``os.replace``) so a crash
mid-write can never corrupt the store; a missing / empty / corrupt file is
tolerated by starting from an empty store. Every call is a full
load-modify-write — single-writer by design, mirroring
:class:`agent_exchange.market.reputation.JsonReputationStore`.
"""

from __future__ import annotations

import json
import os
import tempfile
from typing import Any

from .types import (
    DEFAULT_THRESHOLDS,
    BaselineMode,
    BaselineWindow,
    DriftThresholds,
    JobTelemetry,
    SampleSizeTier,
)

# One day in epoch milliseconds — the recency-window unit (ported from
# ``baseline_window.rs``: ``window_days * 86_400_000``).
_MS_PER_DAY = 86_400_000


def _row_to_dict(row: JobTelemetry) -> dict[str, Any]:
    """Serialize a :class:`JobTelemetry` row to a JSON-safe dict.

    Every field is written, including the (possibly empty) ``tool_call_counts`` /
    ``model_call_counts`` dicts and an ``est_cost_usd`` that may be ``None`` (a
    cost-blind row — preserved as ``null`` so the cost baseline can drop it).
    """
    return {
        "agent_id": row.agent_id,
        "job_id": row.job_id,
        "task": row.task,
        "started_at_ms": int(row.started_at_ms),
        "model": row.model,
        "est_cost_usd": row.est_cost_usd,  # float | None, preserved as-is
        "latency_ms": int(row.latency_ms),
        "llm_call_count": int(row.llm_call_count),
        "total_input_tokens": int(row.total_input_tokens),
        # Copy the dicts so the stored value can't alias the caller's mutable one.
        "tool_call_counts": {str(k): int(v) for k, v in row.tool_call_counts.items()},
        "model_call_counts": {str(k): int(v) for k, v in row.model_call_counts.items()},
    }


def _dict_to_row(raw: dict[str, Any]) -> JobTelemetry:
    """Deserialize a stored dict back into a :class:`JobTelemetry` row.

    Tolerant of missing keys: each falls back to the dataclass default, so an
    older / partial row never crashes the read. ``est_cost_usd`` is left as
    ``None`` when absent (cost-blind), never coerced to ``0.0``.
    """
    est = raw.get("est_cost_usd", None)
    return JobTelemetry(
        agent_id=str(raw.get("agent_id", "")),
        job_id=str(raw.get("job_id", "")),
        task=raw.get("task", None),
        started_at_ms=int(raw.get("started_at_ms", 0)),
        model=str(raw.get("model", "")),
        est_cost_usd=(None if est is None else float(est)),
        latency_ms=int(raw.get("latency_ms", 0)),
        llm_call_count=int(raw.get("llm_call_count", 0)),
        total_input_tokens=int(raw.get("total_input_tokens", 0)),
        tool_call_counts={
            str(k): int(v) for k, v in (raw.get("tool_call_counts") or {}).items()
        },
        model_call_counts={
            str(k): int(v) for k, v in (raw.get("model_call_counts") or {}).items()
        },
    )


class JsonTelemetryStore:
    """A per-agent telemetry store backed by a single JSON file.

    Parameters
    ----------
    path:
        Filesystem path to the JSON store. Parent directories and the file
        itself are created on first write; the file need not exist up front.

    Notes
    -----
    Every :meth:`record` does a full load-modify-write of the file so concurrent
    processes don't clobber each other's whole-file state (last writer wins at
    the granularity of one record; this layer is single-writer by design).
    Reads (:meth:`rows_for`, :meth:`baseline`) re-load from disk each call, so a
    fresh store always reflects the latest committed rows.
    """

    def __init__(self, path: str) -> None:
        self._path = path

    # ----------------------------------------------------------------- writes

    def record(self, row: JobTelemetry) -> None:
        """Append ``row`` to its agent's row list and persist atomically.

        Parameters
        ----------
        row:
            The completed-job telemetry row to store. Filed under
            ``row.agent_id``; rows are appended, never deduplicated, so a
            re-recorded ``(agent, job)`` produces a second entry (the caller owns
            idempotency, matching the reputation store's fold-once contract).

        Notes
        -----
        Full load-modify-write: the agent's existing list is loaded, the
        serialized row appended, and the whole store rewritten atomically.
        """
        store = self._load()
        rows = store.get(row.agent_id)
        if not isinstance(rows, list):
            rows = []
        rows.append(_row_to_dict(row))
        store[row.agent_id] = rows
        self._save(store)

    # ----------------------------------------------------------------- reads

    def rows_for(self, agent_id: str) -> tuple[JobTelemetry, ...]:
        """Return all stored rows for ``agent_id``, oldest first.

        Parameters
        ----------
        agent_id:
            The worker whose telemetry rows to read.

        Returns
        -------
        tuple[JobTelemetry, ...]
            Deserialized rows sorted by ``started_at_ms`` ascending (the
            window-ordering key). Empty when the agent has never been recorded
            or the file is missing / corrupt. Non-dict entries are skipped
            defensively.
        """
        store = self._load()
        raw_rows = store.get(agent_id)
        if not isinstance(raw_rows, list):
            return ()
        rows = [_dict_to_row(r) for r in raw_rows if isinstance(r, dict)]
        rows.sort(key=lambda r: r.started_at_ms)
        return tuple(rows)

    def baseline(
        self,
        agent_id: str,
        *,
        task: str | None,
        mode: BaselineMode,
        window_days: int,
        now_ms: int,
        exclude_job_id: str | None = None,
        thresholds: DriftThresholds = DEFAULT_THRESHOLDS,
    ) -> BaselineWindow:
        """Assemble the baseline window a current row is judged against.

        Ports ``baseline_window.rs::load_baseline_window`` +
        ``shared_rules.rs::resolve_baseline_mode``, adapted from the per-run span
        DB to per-``(agent, job)`` JSON rows.

        Parameters
        ----------
        agent_id:
            The worker whose prior rows form the baseline.
        task:
            The current job's task tag. In ``PER_TASK`` mode the baseline is
            filtered to rows with this exact task; in ``GLOBAL`` mode it is used
            only for the per-task *count* (the cohort stays all-task).
        mode:
            Which cohort the caller wants the ``samples`` drawn from. ``PER_TASK``
            → the same-task subset (``task_filter=task``); ``GLOBAL`` → all
            recency-passing rows (``task_filter=None``).
        window_days:
            Recency window width. A row is kept iff
            ``now_ms - started_at_ms <= window_days * 86_400_000`` — i.e. its
            start is within the window (boundary inclusive).
        now_ms:
            "Now" in epoch milliseconds (passed in for determinism, mirroring the
            Rust ``now_ms`` test seam).
        exclude_job_id:
            If given, the row for this job is dropped first — a job is never part
            of its own baseline (ports the ``run_id == current_run_id`` skip).
        thresholds:
            Supplies ``bootstrap_min_runs`` (default 30) — the per-task sample
            count at which the tier promotes to ``PER_TASK_BOOTSTRAP``.

        Returns
        -------
        BaselineWindow
            ``samples`` (the cohort for the requested ``mode``), ``mode``,
            ``tier``, ``task_filter``, ``window_days``, and the two raw counts
            (``global_count`` = all recency-passing rows; ``per_task_count`` =
            the same-task subset of those).

        Tier classification (ported from ``resolve_baseline_mode``)
        -----------------------------------------------------------
        The Rust ladder (``shared_rules.rs`` lines 124-139) is::

            per_task >= bootstrap_min            -> PER_TASK_BOOTSTRAP (PerTask)
            per_task >= 3                          -> PER_TASK_SIMPLE    (PerTask)
            global   >= 2                          -> GLOBAL_ROLLING     (Global)
            else                                   -> NO_BASELINE        (Global)

        Two faithful-to-Rust divergences from the brief's "≥1" shape are noted
        here because the brief said: follow the Rust, comment the difference.

        * **PER_TASK simple floor is ≥3, not ≥1.** The Rust requires three
          same-task runs before a per-task baseline; one or two same-task rows do
          NOT yield ``PER_TASK_SIMPLE``.
        * **GLOBAL floor is ≥2, not ≥1.** The Rust requires two total runs before
          ``GLOBAL_ROLLING``; a single row stays ``NO_BASELINE``.

        Because this method takes an *explicit* ``mode`` (the Rust *derived* it),
        the ladder is applied as a tier classifier consistent with the requested
        cohort: in ``PER_TASK`` mode the tier comes from ``per_task_count`` (and
        can fall back to ``GLOBAL_ROLLING`` / ``NO_BASELINE`` exactly as the Rust
        does when per-task is thin); in ``GLOBAL`` mode the tier is
        ``GLOBAL_ROLLING`` when ``global_count >= 2`` else ``NO_BASELINE``. Zero
        usable samples is always ``NO_BASELINE`` — there is nothing to compare
        against.
        """
        rows = list(self.rows_for(agent_id))

        # A job is never part of its own baseline (ports run_id != current_run).
        if exclude_job_id is not None:
            rows = [r for r in rows if r.job_id != exclude_job_id]

        # Recency filter: keep rows whose start is within the window. Boundary is
        # inclusive (delta == window_days * 86_400_000 stays), matching the Rust
        # `started_at_ms >= window_start_ms` predicate (window_start = now - W).
        window_ms = window_days * _MS_PER_DAY
        recent = [r for r in rows if (now_ms - r.started_at_ms) <= window_ms]

        # Count bookkeeping (ports global_count / per_task_count). global_count is
        # ALL recency-passing rows; per_task_count is the same-task subset.
        global_count = len(recent)
        per_task_rows = (
            [r for r in recent if r.task == task] if task is not None else []
        )
        per_task_count = len(per_task_rows)

        # Pick the cohort by the requested mode (ports the `match mode` block).
        if mode is BaselineMode.PER_TASK:
            samples = tuple(per_task_rows)
            task_filter: str | None = task
        else:  # BaselineMode.GLOBAL
            samples = tuple(recent)
            task_filter = None

        tier = self._classify_tier(
            mode=mode,
            per_task_count=per_task_count,
            global_count=global_count,
            bootstrap_min=thresholds.bootstrap_min_runs,
        )

        return BaselineWindow(
            samples=samples,
            mode=mode,
            tier=tier,
            task_filter=task_filter,
            window_days=window_days,
            global_count=global_count,
            per_task_count=per_task_count,
        )

    # --------------------------------------------------------- tier classifier

    @staticmethod
    def _classify_tier(
        *,
        mode: BaselineMode,
        per_task_count: int,
        global_count: int,
        bootstrap_min: int,
    ) -> SampleSizeTier:
        """Sample-size tier for the requested cohort (ports ``resolve_baseline_mode``).

        See :meth:`baseline` for the ported ladder and the two faithful-to-Rust
        divergences from the brief's "≥1" shape (per-task floor ≥3, global floor
        ≥2). Zero usable samples → ``NO_BASELINE`` regardless of mode.
        """
        if mode is BaselineMode.PER_TASK:
            if per_task_count >= bootstrap_min:
                return SampleSizeTier.PER_TASK_BOOTSTRAP
            if per_task_count >= 3:
                return SampleSizeTier.PER_TASK_SIMPLE
            # Per-task too thin — fall back exactly like the Rust ladder does.
            if global_count >= 2:
                return SampleSizeTier.GLOBAL_ROLLING
            return SampleSizeTier.NO_BASELINE
        # GLOBAL mode: the cohort is all rows; only the global floor applies.
        if global_count >= 2:
            return SampleSizeTier.GLOBAL_ROLLING
        return SampleSizeTier.NO_BASELINE

    # ------------------------------------------------------------ persistence

    def _load(self) -> dict[str, Any]:
        """Load the raw store, tolerating a missing / empty / corrupt file."""
        try:
            with open(self._path, encoding="utf-8") as fh:
                data = json.load(fh)
        except (FileNotFoundError, ValueError, OSError):
            # Missing, empty, or corrupt JSON -> start fresh rather than crash.
            return {}
        if not isinstance(data, dict):
            return {}
        return data

    def _save(self, store: dict[str, Any]) -> None:
        """Atomically write the raw store (temp file in the same dir + replace)."""
        directory = os.path.dirname(os.path.abspath(self._path))
        os.makedirs(directory, exist_ok=True)

        # Write to a temp file in the SAME directory so os.replace is atomic
        # (a cross-filesystem rename would not be).
        fd, tmp_path = tempfile.mkstemp(dir=directory, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(store, fh, indent=2, sort_keys=True)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp_path, self._path)
        except BaseException:
            # Don't leave a stray temp file behind on any failure.
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
