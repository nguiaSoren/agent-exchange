"""JSON-backed reputation store for the Agent Exchange bidding layer.

Implements `JsonReputationStore`, a file-persisted `ReputationStore` (see
`schema.py` for the frozen `ReputationRecord` and the `ReputationStore`
Protocol). The store keeps EXACT raw counts on disk so that folding in a job
outcome never loses precision, and derives the rate/fraction floats lazily on
`get`. Writes are atomic (temp file + `os.replace`) so a crash mid-write can
never corrupt the store, and a missing / empty / corrupt file is tolerated by
starting from an empty store.

On-disk schema (a single JSON object keyed by worker id)::

    {
      "<worker>": {
        "n_jobs": int,                 # total jobs folded in
        "n_success": int,              # how many were a clean/paid success
        "sum_pay_fraction": float,     # running sum of pay fractions
        "per_specialty": {
          "<specialty>": {"n_jobs": int, "n_success": int, "sum_pay_fraction": float},
          ...
        }
      },
      ...
    }

Derivation (Beta(1,1) / Laplace prior on the success rate)::

    success_rate     = (1 + n_success) / (2 + n_jobs)        # -> 0.5 at n_jobs == 0
    avg_pay_fraction = sum_pay_fraction / n_jobs  (else 0.5)  # neutral prior when unseen
"""

from __future__ import annotations

import json
import os
import tempfile
from typing import Any

from .schema import ReputationRecord


# Neutral-prior constants — a never-seen worker is treated as average, not bad.
_PRIOR_SUCCESS_RATE = 0.5
_PRIOR_PAY_FRACTION = 0.5


def _derive_success_rate(n_jobs: int, n_success: int) -> float:
    """Beta(1,1) posterior mean: ``(1 + n_success) / (2 + n_jobs)``.

    Starts at 0.5 with no data and is pulled toward the observed success ratio
    as jobs accumulate, while never reaching exactly 0 or 1 on finite data.
    """
    return (1 + n_success) / (2 + n_jobs)


def _derive_avg_pay_fraction(n_jobs: int, sum_pay_fraction: float) -> float:
    """Mean pay fraction, or the neutral prior (0.5) when there is no data."""
    if n_jobs <= 0:
        return _PRIOR_PAY_FRACTION
    return sum_pay_fraction / n_jobs


def _empty_raw() -> dict[str, Any]:
    """A fresh raw-counts record for a previously unseen worker."""
    return {
        "n_jobs": 0,
        "n_success": 0,
        "sum_pay_fraction": 0.0,
        "per_specialty": {},
    }


def _empty_specialty_raw() -> dict[str, Any]:
    """A fresh raw-counts record for a previously unseen specialty."""
    return {"n_jobs": 0, "n_success": 0, "sum_pay_fraction": 0.0}


class JsonReputationStore:
    """A `ReputationStore` backed by a single JSON file of raw outcome counts.

    Parameters
    ----------
    path:
        Filesystem path to the JSON store. Parent directories and the file
        itself are created on first write; the file need not exist up front.

    Notes
    -----
    Every `update` does a full load-modify-write of the file so concurrent
    processes don't clobber each other's whole-file state (last writer wins at
    the granularity of a single update; this layer is single-writer by design).
    The structural type checks against the `ReputationStore` Protocol — no
    inheritance is needed.
    """

    def __init__(self, path: str) -> None:
        self._path = path

    # ----------------------------------------------------------------- reads

    def get(self, worker: str) -> ReputationRecord:
        """Return ``worker``'s reputation, or a neutral prior if never seen.

        `ReputationRecord` is frozen, so a fresh instance is always
        constructed; the floats are derived from the stored raw counts rather
        than persisted, keeping the on-disk representation exact.
        """
        store = self._load()
        raw = store.get(worker)
        if raw is None:
            return ReputationRecord(worker=worker)  # dataclass defaults == neutral prior

        n_jobs = int(raw.get("n_jobs", 0))
        n_success = int(raw.get("n_success", 0))
        sum_pay = float(raw.get("sum_pay_fraction", 0.0))

        per_specialty: dict[str, dict[str, float]] = {}
        for sp, sp_raw in raw.get("per_specialty", {}).items():
            sp_jobs = int(sp_raw.get("n_jobs", 0))
            sp_success = int(sp_raw.get("n_success", 0))
            sp_pay = float(sp_raw.get("sum_pay_fraction", 0.0))
            per_specialty[sp] = {
                "success_rate": _derive_success_rate(sp_jobs, sp_success),
                "avg_pay_fraction": _derive_avg_pay_fraction(sp_jobs, sp_pay),
                "n_jobs": float(sp_jobs),
            }

        return ReputationRecord(
            worker=worker,
            n_jobs=n_jobs,
            success_rate=_derive_success_rate(n_jobs, n_success),
            avg_pay_fraction=_derive_avg_pay_fraction(n_jobs, sum_pay),
            per_specialty=per_specialty,
        )

    # ---------------------------------------------------------------- writes

    def update(
        self,
        worker: str,
        *,
        success: bool,
        pay_fraction: float,
        specialty: str | None = None,
    ) -> None:
        """Fold one job outcome into ``worker``'s record and persist it.

        Parameters
        ----------
        worker:
            Worker id whose record is being updated.
        success:
            Whether the job was a clean / paid success.
        pay_fraction:
            Fraction (0..1) of the authorized budget this job's findings earned.
        specialty:
            Optional specialty tag; when given, the same outcome is also folded
            into that worker's per-specialty breakdown.

        Raises
        ------
        ValueError:
            If ``pay_fraction`` is outside ``[0.0, 1.0]``.
        """
        if not (0.0 <= pay_fraction <= 1.0):
            raise ValueError(
                f"pay_fraction must be in [0.0, 1.0], got {pay_fraction!r}"
            )

        store = self._load()
        raw = store.get(worker)
        if raw is None or not isinstance(raw, dict):
            raw = _empty_raw()

        inc_success = 1 if success else 0

        raw["n_jobs"] = int(raw.get("n_jobs", 0)) + 1
        raw["n_success"] = int(raw.get("n_success", 0)) + inc_success
        raw["sum_pay_fraction"] = float(raw.get("sum_pay_fraction", 0.0)) + pay_fraction

        if specialty is not None:
            per_specialty = raw.setdefault("per_specialty", {})
            sp_raw = per_specialty.get(specialty)
            if not isinstance(sp_raw, dict):
                sp_raw = _empty_specialty_raw()
            sp_raw["n_jobs"] = int(sp_raw.get("n_jobs", 0)) + 1
            sp_raw["n_success"] = int(sp_raw.get("n_success", 0)) + inc_success
            sp_raw["sum_pay_fraction"] = (
                float(sp_raw.get("sum_pay_fraction", 0.0)) + pay_fraction
            )
            per_specialty[specialty] = sp_raw

        store[worker] = raw
        self._save(store)

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
