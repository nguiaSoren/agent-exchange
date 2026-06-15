"""Locked types for the gate's audit trail — lifecycle hooks, signed receipts, ledger.

Two DISTINCT guarantees (keep them separate — they are not the same thing):
  * **Signed receipt** — a per-job, EIP-191 key-SIGNED proof that binds the verified
    work (the deliverable + per-claim verdicts) to the payment (per-worker settled
    amount + on-chain tx). Anyone can verify it with the signer's address (ecrecover).
  * **Hash-chained ledger** — an append-only local trail of EVERY gate event (verify
    ok/fail, settle, withhold), where each entry hashes the previous one. Tamper-
    EVIDENT (you can detect edits), but NOT key-signed.

The gate fires lifecycle `GateHooks` at each step; a recorder turns those into ledger
entries, and a signed receipt is built from the final settlement.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


# ── Lifecycle hooks ──────────────────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class GateEvent:
    """One lifecycle event from the settlement gate (passed to the hooks)."""

    job_id: str
    event: str                  # "verify_ok" | "verify_fail" | "before_settle" | "settled" | "withheld"
    worker: str
    authorized_atomic: int
    settled_atomic: int = 0
    tx_hash: str | None = None
    status: str = ""
    detail: str = ""


@runtime_checkable
class GateHooks(Protocol):
    """Lifecycle hooks the gate calls (all awaited). A no-op default is fine; the
    recorder implements them to write the ledger trail."""

    async def on_after_verify(self, ev: GateEvent) -> None: ...
    async def on_before_settle(self, ev: GateEvent) -> None: ...
    async def on_after_settle(self, ev: GateEvent) -> None: ...
    async def on_verify_failure(self, ev: GateEvent) -> None: ...
    async def on_withhold(self, ev: GateEvent) -> None: ...


# ── Signed receipt (key-signed, EIP-191) ─────────────────────────────────────

@dataclass(frozen=True, slots=True)
class WorkerReceiptLine:
    """Per-worker line in a receipt: what was verified, what was paid, the tx."""

    worker: str
    verdict_summary: str        # e.g. "4 confirmed, 1 partial, 0 unsupported"
    authorized_atomic: int
    settled_atomic: int
    tx_hash: str | None
    status: str


@dataclass(frozen=True, slots=True)
class Receipt:
    """The canonical proof-of-work-and-payment for one job (the thing that gets signed)."""

    job_id: str
    deliverable_hash: str       # sha256 over the graded deliverable — binds the WORK
    gate_passed: bool
    pay_fraction: float
    timestamp: str              # ISO-8601 UTC
    workers: tuple[WorkerReceiptLine, ...]


@dataclass(frozen=True, slots=True)
class SignedReceipt:
    """A `Receipt` + its EIP-191 signature. Verify with ``signer_address`` via ecrecover."""

    receipt: Receipt
    signer_address: str         # 0x… (recovers from the signature)
    signature: str              # 0x… EIP-191 personal_sign over the receipt's canonical hash


# ── Hash-chained ledger entry (tamper-evident, NOT signed) ───────────────────

@dataclass(frozen=True, slots=True)
class LedgerEntry:
    """One append-only ledger row. ``entry_hash`` chains on ``prev_hash``."""

    seq: int
    timestamp: str              # ISO-8601 UTC
    event: str
    payload: dict
    prev_hash: str              # the previous entry's entry_hash ("" / genesis for the first)
    entry_hash: str             # sha256(prev_hash + canonical(seq,timestamp,event,payload))
