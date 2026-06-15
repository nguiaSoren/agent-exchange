"""Locked types for the x402 verify→settle payment gate.

The gate turns a verified deliverable into real money movement: the buyer authorizes
payment up front, the platform `verify`s the authorization, the team does the work, the
verifier grades it, and the platform `settle`s — per worker — ONLY if the work passes.

Settlement model (decided with Soren):
  * **No-fabrication hard gate** — if ANY claim in the deliverable is `unsupported`
    (fabricated), the WHOLE job is withheld: no money moves for anyone ("$0 for
    fabricated work").
  * **Per-worker prorate (upto scheme)** — on pass, each hired worker is paid
    ``its_bid × pay_fraction`` to its OWN wallet, where confirmed claims earn full
    credit and partial claims earn half (LENIENT). Money is settled via x402's `upto`
    scheme so we can settle LESS than the authorized maximum.

These frozen types are the seam the x402 wrapper, the gate logic, and the tests all
code against.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@runtime_checkable
class PaymentGate(Protocol):
    """The injectable payment seam — verify up front, settle (≤max) conditionally.

    The real implementation (``X402Gate``) wraps the x402 facilitator + the buyer's
    signer + network/asset config; tests inject a fake. ``requirement`` and ``payload``
    are opaque pass-through objects (x402 library types live behind this seam).
    """

    def build_requirement(self, *, amount_atomic: int, pay_to: str) -> object:
        """A payment requirement for ``amount_atomic`` (the worker's max) → ``pay_to``."""
        ...

    async def authorize(self, requirement: object) -> object:
        """The buyer signs an authorization for ``requirement`` → an opaque payload."""
        ...

    async def verify(self, payload: object, requirement: object) -> bool:
        """Validate the authorization WITHOUT moving money. True ⇒ good to settle later."""
        ...

    async def settle(self, payload: object, requirement: object, *, amount_atomic: int) -> str:
        """Move ``amount_atomic`` (≤ the authorized max) on-chain. Returns the tx hash."""
        ...


@dataclass(frozen=True, slots=True)
class WorkerSettlement:
    """The settlement outcome for ONE hired worker."""

    worker: str
    pay_to: str                 # the worker's payout wallet address (0x…)
    authorized_atomic: int      # the worker's signed maximum (its bid, USDC atomic, 6dp)
    settled_atomic: int         # what actually moved on-chain (0 if withheld / failed)
    tx_hash: str | None         # the on-chain settle tx (None if nothing settled)
    status: str                 # "settled" | "withheld" | "verify_failed" | "settle_failed"


@dataclass(frozen=True, slots=True)
class JobSettlement:
    """The settlement outcome for a whole job: the gate decision + per-worker results."""

    gate_passed: bool           # the no-fabrication gate (False ⇒ everyone withheld)
    pay_fraction: float         # 0..1 of each worker's authorized max (the prorate)
    n_unsupported: int          # fabricated-claim count; >0 is what fails the gate
    workers: tuple[WorkerSettlement, ...]

    @property
    def total_settled_atomic(self) -> int:
        return sum(w.settled_atomic for w in self.workers)

    @property
    def total_authorized_atomic(self) -> int:
        return sum(w.authorized_atomic for w in self.workers)

    @property
    def total_withheld_atomic(self) -> int:
        return self.total_authorized_atomic - self.total_settled_atomic
