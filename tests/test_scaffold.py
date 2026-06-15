"""Scaffold tests — determinism idempotency + the immutable trace round-trip.

Runnable two ways:
  - `python3 tests/test_scaffold.py`   (no pytest needed — the __main__ runner)
  - `pytest`                            (once dev extras are installed)
"""

from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from agent_exchange.determinism import enforce_determinism
from agent_exchange.metrics import (
    ClaimRecord,
    JobTrace,
    StageTimings,
    TraceWriter,
    monotonic_ns,
    usdc,
)


def test_determinism_idempotent_and_reseeds():
    r1 = enforce_determinism(1)
    assert r1.seed == 1
    import random
    a = [random.random() for _ in range(5)]
    enforce_determinism(1)  # same seed → same stream
    b = [random.random() for _ in range(5)]
    assert a == b
    enforce_determinism(2)  # different seed → different stream
    c = [random.random() for _ in range(5)]
    assert a != c


def test_usdc_atomic_and_no_floats():
    assert usdc(0.001) == 1000
    assert usdc(1) == 1_000_000
    assert isinstance(usdc(0.42), int)


def test_jobtrace_immutable_and_balanced():
    claim_ok = ClaimRecord("w1", "clause 7 caps liability at $5M", "confirmed", 0.93)
    claim_lie = ClaimRecord("w2", "clause 12 waives all indemnity", "unsupported", 0.88)
    assert claim_ok.claim_hash and len(claim_ok.claim_hash) == 64  # auto sha256

    start = monotonic_ns()
    timings = StageTimings(started_ns=start, post_ns=start + 5_000_000, settle_ns=start + 90_000_000)

    trace = JobTrace(
        job_id="job-1",
        job_kind="contract-clause-audit",
        job_spec="acme-vendor-msa.pdf",
        worker_ids=("w1", "w2"),
        claims=(claim_ok, claim_lie),
        amount_authorized_atomic=usdc(0.05),
        amount_settled_atomic=usdc(0.025),     # paid only the verified half
        amount_withheld_atomic=usdc(0.05) - usdc(0.025),
        settled=True,
        tx_hash="0xdeadbeef",
        seeded_liar=True,
        timings=timings,
        seed=1,
    )

    # immutability (frozen dataclass)
    try:
        trace.job_id = "mutated"  # type: ignore[misc]
        raise AssertionError("JobTrace should be immutable")
    except (AttributeError, Exception):
        pass

    # derived views the metric step uses
    assert trace.n_claims == 2
    assert trace.n_unsupported == 1
    assert trace.job_spec_hash and len(trace.job_spec_hash) == 64
    assert trace.timings.total_ms() == 90.0


def test_trace_writer_append_only_roundtrip():
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "traces", "jobs.jsonl")
        w = TraceWriter(path)
        start = monotonic_ns()
        for i in range(3):
            w.write(
                JobTrace(
                    job_id=f"job-{i}",
                    job_kind="contract-clause-audit",
                    job_spec=f"doc-{i}.pdf",
                    worker_ids=("w1",),
                    claims=(ClaimRecord("w1", f"claim {i}", "confirmed", 0.9),),
                    amount_authorized_atomic=usdc(0.01),
                    amount_settled_atomic=usdc(0.01),
                    amount_withheld_atomic=0,
                    settled=True,
                    tx_hash=None,
                    seeded_liar=False,
                    timings=StageTimings(started_ns=start, settle_ns=start + 1_000_000),
                    seed=1,
                )
            )
        rows = w.read_all()
        assert len(rows) == 3
        assert {r["job_id"] for r in rows} == {"job-0", "job-1", "job-2"}
        assert w.enrichment_path.endswith(".enrichment.jsonl")


def _run_all():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"  ✓ {fn.__name__}")
    print(f"\n{len(fns)} passed")


if __name__ == "__main__":
    _run_all()
