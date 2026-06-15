"""EIP-191 signed receipts — a verifiable proof binding verified WORK to PAYMENT.

A **receipt** is the canonical, per-job record of what was verified and what was paid:
a content hash over the graded deliverable (the WORK), the gate decision + prorate, a
timestamp, and one line per worker (its verdict summary + the on-chain settlement). A
**signed receipt** wraps that record with an EIP-191 ``personal_sign`` signature over its
canonical bytes, so anyone holding the signer's address can recover the signer with
``ecrecover`` and confirm the receipt was not altered — a cryptographic attestation that
binds the verified work to the money that moved for it.

Trust model: the deliverable hash binds the WORK content (tamper any graded finding and
the hash changes), and the signature binds the whole receipt to a key (tamper any field
and recovery yields a different address). Neither requires trusting this process at read
time — verification is offline and key-based.

Determinism is the whole game: ``sign`` and ``verify_receipt`` MUST agree on the EXACT
canonical bytes. Both route through ``_receipt_message`` → ``canonical_json`` (sorted
keys, no whitespace), so the same ``Receipt`` always serializes to the same message and a
round-trip (``build_receipt`` → ``sign`` → ``verify_receipt``) returns ``True`` while any
mutation returns ``False``.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict

from eth_account import Account
from eth_account.messages import encode_defunct

from ..audit.report import AuditedFinding
from ..audit.room_audit_types import RoomAuditResult
from ..redact import Policy, default_policy, redact_obj
from ..verify.schema import Verdict
from .audit_types import Receipt, SignedReceipt, WorkerReceiptLine
from .types import JobSettlement

# Write-time PII redaction policy for the receipt's WORK content (conservative,
# default-ON). The graded findings are redacted BEFORE deliverable_hash + sign, so
# the hash and EIP-191 signature commit to — and verify_receipt round-trips over —
# the redacted receipt. verify_receipt recomputes the same canonical bytes from the
# embedded (already-redacted) receipt, so a genuine receipt still recovers to its
# signer.
_RECEIPT_REDACT_POLICY: Policy = default_policy()


def canonical_json(obj: object) -> str:
    """Deterministic JSON for hashing/signing: sorted keys, no whitespace.

    The same logical value always serializes to the same string, so two parties (signer
    and verifier) derive identical bytes. ``ensure_ascii=True`` keeps the output pure ASCII
    so the byte encoding is unambiguous across platforms.
    """
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _graded_deliverable(
    deliverable: RoomAuditResult, *, redact_policy: Policy | None = None
) -> list[dict]:
    """The deliverable's graded findings as a list of plain dicts (verdict as its string
    value) — the exact content that ``deliverable_hash`` commits to.

    PII is redacted from the WORK content (claim / clause_ref strings) BEFORE it is
    returned, so the deliverable hash + the signed receipt commit only to redacted
    text. Redaction is applied to the persisted artifact only — the in-flight verifier
    already graded the FULL findings before this point.
    """
    pol = redact_policy if redact_policy is not None else _RECEIPT_REDACT_POLICY
    rows: list[dict] = []
    for af in deliverable.all_audited:
        f = af.finding
        rows.append(
            {
                "worker": f.worker,
                "clause_ref": f.clause_ref,
                "claim": f.claim,
                "severity": f.severity,
                "verdict": af.verdict.verdict.value,
            }
        )
    return redact_obj(rows, pol)  # type: ignore[return-value]


def deliverable_hash(deliverable: RoomAuditResult, *, redact_policy: Policy | None = None) -> str:
    """``"0x" + sha256`` over the canonical JSON of the graded deliverable.

    Binds the WORK content: every graded finding (worker, clause_ref, claim, severity, and
    its verdict) is committed to. Changing any of them changes the hash, so a receipt's
    ``deliverable_hash`` is a tamper-evident fingerprint of exactly what was verified.
    """
    payload = canonical_json(_graded_deliverable(deliverable, redact_policy=redact_policy))
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return "0x" + digest


def _verdict_summary_for(deliverable: RoomAuditResult, worker: str) -> str:
    """Compute "N confirmed, M partial, K unsupported" for one worker from the graded
    findings whose ``finding.worker == worker``."""
    n_confirmed = n_partial = n_unsupported = 0
    for af in deliverable.all_audited:
        if af.finding.worker != worker:
            continue
        v = af.verdict.verdict
        if v is Verdict.CONFIRMED:
            n_confirmed += 1
        elif v is Verdict.PARTIAL:
            n_partial += 1
        elif v is Verdict.UNSUPPORTED:
            n_unsupported += 1
    return f"{n_confirmed} confirmed, {n_partial} partial, {n_unsupported} unsupported"


def build_receipt(
    job_id: str,
    deliverable: RoomAuditResult,
    settlement: JobSettlement,
    *,
    timestamp: str,
    verdicts_by_worker: dict[str, str] | None = None,
    redact_policy: Policy | None = None,
) -> Receipt:
    """Assemble the per-job ``Receipt`` from the graded deliverable + the settlement.

    The deliverable supplies the WORK fingerprint (``deliverable_hash``) and the per-worker
    verdict summaries; the settlement supplies the gate decision, the prorate, and each
    worker's on-chain outcome. One ``WorkerReceiptLine`` is emitted per ``settlement.workers``
    (the workers that were actually hired/settled), in settlement order.

    ``verdicts_by_worker`` lets the caller pass precomputed per-worker summaries (e.g. when
    the grading counts were tallied elsewhere); when absent or missing a worker, the summary
    is computed from the deliverable's findings for that worker.
    """
    lines: list[WorkerReceiptLine] = []
    for w in settlement.workers:
        if verdicts_by_worker is not None and w.worker in verdicts_by_worker:
            summary = verdicts_by_worker[w.worker]
        else:
            summary = _verdict_summary_for(deliverable, w.worker)
        lines.append(
            WorkerReceiptLine(
                worker=w.worker,
                verdict_summary=summary,
                authorized_atomic=w.authorized_atomic,
                settled_atomic=w.settled_atomic,
                tx_hash=w.tx_hash,
                status=w.status,
            )
        )
    return Receipt(
        job_id=job_id,
        deliverable_hash=deliverable_hash(deliverable, redact_policy=redact_policy),
        gate_passed=settlement.gate_passed,
        pay_fraction=settlement.pay_fraction,
        timestamp=timestamp,
        workers=tuple(lines),
    )


def _receipt_message(receipt: Receipt) -> bytes:
    """The EXACT canonical bytes that get signed/verified for a receipt.

    ``sign`` and ``verify_receipt`` both call this so they can never disagree: the receipt
    (a frozen dataclass, nested ``WorkerReceiptLine``s included) is converted to a plain
    dict via ``asdict``, serialized with ``canonical_json`` (sorted keys, no whitespace),
    and UTF-8 encoded. Identical receipts → identical message bytes.
    """
    return canonical_json(asdict(receipt)).encode("utf-8")


class ReceiptSigner:
    """Signs receipts with an EVM key (EIP-191 ``personal_sign``).

    Wraps an ``eth_account`` account; the signature recovers to ``address()``, which is what
    a verifier checks against. Hold the private key only on the signing side — verification
    needs just the public address.
    """

    def __init__(self, private_key: str) -> None:
        self._account = Account.from_key(private_key)

    def address(self) -> str:
        """The signer's checksummed ``0x…`` address (the public verification identity)."""
        return self._account.address

    def sign(self, receipt: Receipt) -> SignedReceipt:
        """Sign ``receipt``'s canonical bytes with EIP-191 ``personal_sign``.

        The message is ``_receipt_message(receipt)`` wrapped by ``encode_defunct`` (the
        ``\\x19Ethereum Signed Message`` prefix). Returns a ``SignedReceipt`` carrying the
        signer's address and the ``0x``-prefixed hex signature. Round-trips with
        ``verify_receipt``.
        """
        message = encode_defunct(primitive=_receipt_message(receipt))
        signed = self._account.sign_message(message)
        return SignedReceipt(
            receipt=receipt,
            signer_address=self._account.address,
            signature="0x" + bytes(signed.signature).hex(),
        )


def verify_receipt(signed: SignedReceipt) -> bool:
    """Verify a ``SignedReceipt``: recover the signer over the SAME canonical message and
    compare to the claimed address (checksum-insensitive).

    Recomputes ``_receipt_message`` from the embedded receipt, so any mutation of any
    receipt field (including a worker line) yields different bytes → a different recovered
    address → ``False``. A genuine, untampered receipt recovers to ``signer_address`` →
    ``True``.
    """
    try:
        message = encode_defunct(primitive=_receipt_message(signed.receipt))
        recovered = Account.recover_message(message, signature=signed.signature)
    except Exception:
        return False
    return recovered.lower() == signed.signer_address.lower()


def make_receipt_signer(private_key: str) -> ReceiptSigner:
    """Construct a :class:`ReceiptSigner` from a private key (convenience factory)."""
    return ReceiptSigner(private_key)
