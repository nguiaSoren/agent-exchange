"""Turn the settlement gate's lifecycle hooks into a tamper-evident audit trail.

`ReceiptLedgerRecorder` is a `GateHooks` implementation: it is handed to ``settle_job``
and, at every lifecycle step the gate fires (verify ok/fail, before/after settle,
withhold), it appends one entry to a `HashChainedLedger`. The ledger hash-chains each
entry on the previous one, so the trail is TAMPER-EVIDENT — any later edit breaks the
chain and `verify_chain()` catches it.

Two distinct guarantees live here (kept separate on purpose):
  * the **ledger** captures EVERY gate event as it happens (append-only, hash-chained,
    not key-signed) — the running trail;
  * the **signed receipt** (`finalize_receipt`) is the per-job key-signed proof that
    binds the verified work to the payment, and is ALSO anchored as a ``"receipt"``
    entry in the same chain so the receipt's existence is part of the tamper-evident
    record.

A recorder is observation-only: `settle_job` wraps each hook so a recorder that raises
can never break settlement.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
from typing import Callable

from ..audit.room_audit_types import RoomAuditResult
from .audit_types import GateEvent, SignedReceipt
from .ledger import HashChainedLedger
from .receipts import ReceiptSigner, build_receipt
from .types import JobSettlement


def _utc_now_iso() -> str:
    """Default clock: an ISO-8601 UTC timestamp for the current instant."""
    return datetime.now(timezone.utc).isoformat()


class ReceiptLedgerRecorder:
    """A `GateHooks` that records every gate event into a hash-chained ledger.

    Each lifecycle hook appends ONE `LedgerEntry` whose ``event`` is the `GateEvent`'s
    own event string and whose ``payload`` is the event's fields as a plain dict. The
    ledger hash-chains the entries, making the whole trail tamper-evident.

    ``clock`` is injectable so tests can pin timestamps; it must return an ISO-8601 UTC
    string. The default reads the wall clock.
    """

    def __init__(self, ledger: HashChainedLedger, *, clock: Callable[[], str] | None = None) -> None:
        self.ledger = ledger
        self.clock: Callable[[], str] = clock or _utc_now_iso

    def _record(self, ev: GateEvent) -> None:
        """Append one gate event to the ledger (event = ev.event, payload = ev's fields)."""
        self.ledger.append(ev.event, asdict(ev), timestamp=self.clock())

    # ── GateHooks ────────────────────────────────────────────────────────────
    # Every hook writes the same shape of entry — the event string distinguishes them.

    async def on_after_verify(self, ev: GateEvent) -> None:
        self._record(ev)

    async def on_before_settle(self, ev: GateEvent) -> None:
        self._record(ev)

    async def on_after_settle(self, ev: GateEvent) -> None:
        self._record(ev)

    async def on_verify_failure(self, ev: GateEvent) -> None:
        self._record(ev)

    async def on_withhold(self, ev: GateEvent) -> None:
        self._record(ev)

    # ── signed receipt, anchored in the chain ─────────────────────────────────

    def finalize_receipt(
        self,
        job_id: str,
        deliverable: RoomAuditResult,
        settlement: JobSettlement,
        signer: ReceiptSigner,
    ) -> SignedReceipt:
        """Build + sign the job receipt and anchor it as a ``"receipt"`` ledger entry.

        The receipt binds the verified work (deliverable hash + per-worker lines) to the
        payment (settled amounts + txs). It is key-signed (EIP-191) AND recorded in the
        hash chain, so the signed proof is part of the same tamper-evident trail as the
        raw events. Returns the `SignedReceipt`.
        """
        receipt = build_receipt(job_id, deliverable, settlement, timestamp=self.clock())
        signed = signer.sign(receipt)
        self.ledger.append(
            "receipt",
            {
                "job_id": signed.receipt.job_id,
                "deliverable_hash": signed.receipt.deliverable_hash,
                "signer_address": signed.signer_address,
                "signature": signed.signature,
            },
            timestamp=self.clock(),
        )
        return signed
