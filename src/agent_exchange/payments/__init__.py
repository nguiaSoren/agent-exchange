"""Payments — the x402 verify→settle gate, plus signed receipts + a hash-chained ledger.

The gate verifies up front and settles only on pass; lifecycle hooks feed a tamper-
evident ledger of every gate event, and each job yields an EIP-191 signed receipt that
binds the verified work to the payment.
"""

from .audit_types import (
    GateEvent,
    GateHooks,
    LedgerEntry,
    Receipt,
    SignedReceipt,
    WorkerReceiptLine,
)
from .ledger import HashChainedLedger, tamper_check
from .receipts import (
    ReceiptSigner,
    build_receipt,
    deliverable_hash,
    make_receipt_signer,
    verify_receipt,
)
from .recorder import ReceiptLedgerRecorder
from .settlement import settle_job
from .types import JobSettlement, PaymentGate, WorkerSettlement
from .x402_gate import X402Gate, make_x402_gate

__all__ = [
    # the gate
    "settle_job", "PaymentGate", "WorkerSettlement", "JobSettlement",
    "X402Gate", "make_x402_gate",
    # lifecycle hooks
    "GateHooks", "GateEvent",
    # signed receipts (key-signed)
    "Receipt", "WorkerReceiptLine", "SignedReceipt",
    "build_receipt", "deliverable_hash", "ReceiptSigner", "make_receipt_signer",
    "verify_receipt",
    # hash-chained ledger (tamper-evident)
    "LedgerEntry", "HashChainedLedger", "tamper_check",
    # the recorder that ties hooks → ledger + receipts
    "ReceiptLedgerRecorder",
]
