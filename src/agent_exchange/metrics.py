"""Immutable per-job trace schema + append-only writer — the `/metrics` layer.

This is the instrumentation layer: every job the marketplace runs writes ONE
immutable ``JobTrace`` row from which the headline metric is later derived
("$X settled, $0 paid for fabricated work, N false claims caught & withheld").
Instrumenting up front is what makes the number REAL instead of invented — you
can only report what you measured.

Schema pattern (immutable measurement rows):

  - **Immutable rows.** ``JobTrace`` / ``ClaimRecord`` / ``StageTimings`` are
    ``frozen=True, slots=True``. Once a row is flushed to the trace, NO code path
    mutates it. Post-hoc analysis (enrichment) writes to a SEPARATE file
    (``*.enrichment.jsonl``), never back into the canonical trace.
  - **Monotonic timing.** Stage timestamps are ``time.monotonic_ns()`` — never
    ``time.time()`` (wall clock is non-monotonic under NTP → negative latencies).
    Invariant: every stage end ≥ its start. ``wall_clock_ns`` is recorded once,
    separately, only for human-readable "when did this job run".
  - **Money as atomic ints.** USDC has 6 decimals; amounts are integer atomic
    units (1 USDC = 1_000_000). Never floats for money.
  - **Hashes** (sha256) of the job spec + each claim let same-seed runs be
    verified identical and make the trace tamper-evident on its own terms.

The headline-metric inputs live here: ``amount_settled_atomic``,
``amount_withheld_atomic``, ``claims`` (each with verdict + confidence), and
``seeded_liar`` (so catch-rate is computed only over injected known-bad jobs).
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import asdict, dataclass, field
from typing import Literal

from .redact import Policy, default_policy, redact_obj

# ── vocab ──
Verdict = Literal["confirmed", "partial", "unsupported", "pending"]
Stage = Literal["post", "bid", "hire", "deliver", "verify", "settle"]
_STAGES: tuple[Stage, ...] = ("post", "bid", "hire", "deliver", "verify", "settle")

USDC_DECIMALS = 6  # 1 USDC == 10**6 atomic units


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def usdc(amount: float) -> int:
    """Human USDC → atomic int (e.g. ``usdc(0.001) == 1000``). Money is never a float past this boundary."""
    return round(amount * (10**USDC_DECIMALS))


# ──────────────────────────── records ────────────────────────────

@dataclass(frozen=True, slots=True)
class StageTimings:
    """Monotonic-ns marks for each lifecycle stage boundary.

    Store the END mark of each stage (``post_ns`` = when posting finished, etc.).
    Durations are derived, not stored, so the row can't disagree with itself.
    Use ``None`` for stages a given job didn't reach (e.g. a withheld job has
    no ``settle_ns``).
    """

    started_ns: int                 # monotonic_ns at job start (the zero point)
    post_ns: int | None = None
    bid_ns: int | None = None
    hire_ns: int | None = None
    deliver_ns: int | None = None
    verify_ns: int | None = None
    settle_ns: int | None = None

    def durations_ms(self) -> dict[str, float]:
        """Per-stage elapsed time in ms, measured from the previous reached mark."""
        out: dict[str, float] = {}
        prev = self.started_ns
        for stage in _STAGES:
            mark = getattr(self, f"{stage}_ns")
            if mark is not None:
                out[stage] = (mark - prev) / 1e6
                prev = mark
        return out

    def total_ms(self) -> float | None:
        last = next((getattr(self, f"{s}_ns") for s in reversed(_STAGES) if getattr(self, f"{s}_ns") is not None), None)
        return None if last is None else (last - self.started_ns) / 1e6


@dataclass(frozen=True, slots=True)
class ClaimRecord:
    """One claim a worker made, and the verifier's verdict on it."""

    worker_id: str
    claim_text: str
    verdict: Verdict
    confidence: float                # calibrated confidence in [0,1] from the verifier
    claim_hash: str = ""             # auto-filled in __post_init__

    def __post_init__(self) -> None:
        if not self.claim_hash:
            object.__setattr__(self, "claim_hash", _sha256(self.claim_text))
        if not (0.0 <= self.confidence <= 1.0):
            raise ValueError(f"confidence must be in [0,1], got {self.confidence}")


@dataclass(frozen=True, slots=True)
class JobTrace:
    """The single immutable row written per job. Headline-metric source of truth.

    Once written, immutable. Enrichment (later analysis) → separate file.
    """

    job_id: str
    job_kind: str                    # e.g. "contract-clause-audit"
    job_spec: str                    # the brief / document reference
    worker_ids: tuple[str, ...]
    claims: tuple[ClaimRecord, ...]
    amount_authorized_atomic: int    # what the buyer authorized up front (x402 verify)
    amount_settled_atomic: int       # what was actually paid (x402 settle; 0 on full withhold)
    amount_withheld_atomic: int      # authorized − settled (the "not paid for fabricated work" number)
    settled: bool                    # did any settlement occur?
    tx_hash: str | None              # on-chain settlement tx (Base Sepolia), if settled
    seeded_liar: bool                # True ⇒ this job included an injected known-bad agent (catch-rate denominator)
    timings: StageTimings
    seed: int
    wall_clock_unix: float = field(default_factory=time.time)  # human "when", NOT used for latency math
    job_spec_hash: str = ""

    def __post_init__(self) -> None:
        if self.job_spec_hash == "":
            object.__setattr__(self, "job_spec_hash", _sha256(self.job_spec))
        if self.amount_withheld_atomic != self.amount_authorized_atomic - self.amount_settled_atomic:
            raise ValueError(
                "withheld must equal authorized − settled "
                f"({self.amount_authorized_atomic} − {self.amount_settled_atomic})"
            )

    # convenience views the metric step consumes
    @property
    def n_claims(self) -> int:
        return len(self.claims)

    @property
    def n_unsupported(self) -> int:
        return sum(1 for c in self.claims if c.verdict == "unsupported")

    def to_json(self) -> str:
        return json.dumps(asdict(self), separators=(",", ":"), sort_keys=True)


# ──────────────────────────── writer ────────────────────────────

class TraceWriter:
    """Append-only JSONL writer. One ``JobTrace`` per line; never rewrites a line.

    Uses ``O_APPEND`` so concurrent writers (and the separate-process enrichment
    worker) can't clobber each other's lines. The canonical trace is write-once;
    enrichment goes to ``<path>.enrichment.jsonl`` via ``enrichment_path``.
    """

    def __init__(self, path: str, *, redact_policy: "Policy | None" = None) -> None:
        self.path = path
        # Write-time PII redaction policy. Default = conservative PII (default-ON).
        # The canonical immutable trace must never persist PII; redaction happens on
        # the row's string fields BEFORE the line is written (and before its hashes,
        # which are recomputed over the redacted text below).
        self.redact_policy: Policy = redact_policy if redact_policy is not None else default_policy()
        os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)

    def write(self, trace: JobTrace) -> None:
        # Redact the row's string leaves BEFORE serialization, then recompute the
        # spec/claim hashes over the REDACTED text so the persisted row is internally
        # consistent (its hashes commit to exactly the bytes on disk — no PII).
        row = redact_obj(asdict(trace), self.redact_policy)
        row["job_spec_hash"] = _sha256(row["job_spec"])
        for claim in row.get("claims", ()):
            claim["claim_hash"] = _sha256(claim["claim_text"])
        line = (json.dumps(row, separators=(",", ":"), sort_keys=True) + "\n").encode("utf-8")
        fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
        try:
            os.write(fd, line)  # single atomic append of one line
        finally:
            os.close(fd)

    @property
    def enrichment_path(self) -> str:
        """Where post-hoc analysis writes — NEVER back into the canonical trace."""
        base, ext = os.path.splitext(self.path)
        return f"{base}.enrichment{ext or '.jsonl'}"

    def read_all(self) -> list[dict]:
        """Read raw rows back (for later metric analysis)."""
        if not os.path.exists(self.path):
            return []
        with open(self.path, encoding="utf-8") as f:
            return [json.loads(ln) for ln in f if ln.strip()]

    def write_cost_enrichment(
        self,
        job_id: str,
        model: str,
        cost_usd: float | None,
        *,
        per_call_costs: list[float | None] | None = None,
    ) -> None:
        """Append a cost-per-outcome record to the enrichment file.

        The clearing signal for the marketplace is cost-per-outcome: how much
        did the job actually cost in model-inference USD?  This must be
        measured, not invented.  We record it in the ENRICHMENT file so the
        immutable ``JobTrace`` rows are never mutated (schema contract).

        Args:
            job_id:          Matches the ``JobTrace.job_id`` this enriches.
            model:           The model id used for the job (before resolution).
            cost_usd:        Sum of per-call costs in USD; None when the model's
                             price is unknown (honest — never fabricated).
            per_call_costs:  Optional list of individual call costs (each may be
                             None for the same reason) for fine-grained analysis.
        """
        record = {
            "kind": "cost_enrichment",
            "job_id": job_id,
            "model": model,
            "total_cost_usd": cost_usd,         # None ⇒ unknown price
            "per_call_costs_usd": per_call_costs,
            "enriched_at_unix": time.time(),
        }
        line = (json.dumps(record, separators=(",", ":"), sort_keys=True) + "\n").encode("utf-8")
        fd = os.open(self.enrichment_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
        try:
            os.write(fd, line)
        finally:
            os.close(fd)

    def read_enrichments(self) -> list[dict]:
        """Read all enrichment records (for metric analysis)."""
        if not os.path.exists(self.enrichment_path):
            return []
        with open(self.enrichment_path, encoding="utf-8") as f:
            return [json.loads(ln) for ln in f if ln.strip()]

    def cost_enrichments(self) -> list[dict]:
        """Return only ``cost_enrichment`` records, for the clearing-signal query."""
        return [r for r in self.read_enrichments() if r.get("kind") == "cost_enrichment"]


def monotonic_ns() -> int:
    """The only clock the timing fields should use."""
    return time.monotonic_ns()
