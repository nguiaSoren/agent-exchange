"""JsonReputationStore tests — neutral prior, Bayesian derivation, per-specialty
breakdown, and on-disk PERSISTENCE across store instances.

Runnable two ways:
  - `python3 tests/test_reputation.py`   (no pytest needed — the __main__ runner)
  - `pytest`                              (collected as plain sync test_* functions)

The store keeps EXACT raw counts on disk and derives the float views lazily on
`get`, using a Beta(1,1)/Laplace prior so an unseen worker reads as average (0.5),
not bad. These tests pin that derivation and prove the counts survive a fresh
`JsonReputationStore` opened on the same path (the outcome loop reopens
the store every run).
"""

from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from agent_exchange.market.reputation import JsonReputationStore
from agent_exchange.market.schema import ReputationRecord


def test_unseen_worker_reads_neutral_prior():
    with tempfile.TemporaryDirectory() as d:
        store = JsonReputationStore(os.path.join(d, "rep.json"))
        rec = store.get("never-seen")
        assert isinstance(rec, ReputationRecord)
        assert rec.worker == "never-seen"
        assert rec.n_jobs == 0
        assert rec.success_rate == 0.5        # Beta(1,1) prior at n_jobs == 0
        assert rec.avg_pay_fraction == 0.5    # neutral pay prior when unseen
        assert rec.per_specialty == {}


def test_two_updates_derive_bayesian_rate_and_mean_pay():
    with tempfile.TemporaryDirectory() as d:
        store = JsonReputationStore(os.path.join(d, "rep.json"))
        store.update("w", success=True, pay_fraction=1.0)
        store.update("w", success=False, pay_fraction=0.0)
        rec = store.get("w")
        assert rec.n_jobs == 2
        # success_rate = (1 + n_success) / (2 + n_jobs) = (1 + 1) / (2 + 2) == 0.5
        assert rec.success_rate == (1 + 1) / (2 + 2) == 0.5
        # avg_pay_fraction = (1.0 + 0.0) / 2 == 0.5
        assert rec.avg_pay_fraction == 0.5


def test_third_update_with_specialty_populates_per_specialty():
    with tempfile.TemporaryDirectory() as d:
        store = JsonReputationStore(os.path.join(d, "rep.json"))
        store.update("w", success=True, pay_fraction=1.0)
        store.update("w", success=False, pay_fraction=0.0)
        store.update("w", success=True, pay_fraction=0.8, specialty="liability")
        rec = store.get("w")
        assert rec.n_jobs == 3
        assert "liability" in rec.per_specialty
        sp = rec.per_specialty["liability"]
        # one job folded into the liability breakdown: a clean success at 0.8 pay
        assert sp["n_jobs"] == 1.0
        # success_rate = (1 + 1) / (2 + 1) == 2/3 ; avg_pay_fraction == 0.8 / 1
        assert abs(sp["success_rate"] - (2.0 / 3.0)) < 1e-9
        assert abs(sp["avg_pay_fraction"] - 0.8) < 1e-9


def test_counts_persist_across_a_new_store_on_the_same_path():
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "rep.json")
        writer = JsonReputationStore(path)
        writer.update("w", success=True, pay_fraction=1.0)
        writer.update("w", success=False, pay_fraction=0.0)
        writer.update("w", success=True, pay_fraction=0.8, specialty="liability")

        # A brand-new store object on the SAME path must see the persisted counts.
        reopened = JsonReputationStore(path)
        rec = reopened.get("w")
        assert rec.n_jobs == 3
        assert rec.success_rate == (1 + 2) / (2 + 3)   # 2 successes of 3 jobs
        assert abs(rec.avg_pay_fraction - (1.0 + 0.0 + 0.8) / 3) < 1e-9
        assert rec.per_specialty["liability"]["n_jobs"] == 1.0


def _run_all():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"  ✓ {fn.__name__}")
    print(f"\n{len(fns)} passed")


if __name__ == "__main__":
    _run_all()
