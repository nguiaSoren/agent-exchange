"""Hash-chained, append-only ledger of settlement-gate events — tamper-EVIDENT.

This is the *audit trail* for the settlement gate: every event it emits (verify
ok/fail, before-settle, settle, withhold) is appended as ONE immutable JSONL row,
and each row carries the hash of the row before it (a hash chain). Any edit,
reorder, or deletion of a past row breaks the chain at that point and is detected
by :meth:`HashChainedLedger.verify_chain`.

This is a DIFFERENT guarantee from a key-signed receipt — keep them distinct:

  * **Hash-chained ledger** (this file) — tamper-EVIDENT. Detects after-the-fact
    edits to the local log. No keys, no signatures: anyone holding the file can
    re-derive every hash and confirm nothing was altered, but the chain says
    nothing about *who* wrote it. A holder who rewrites the whole file from a
    chosen genesis can still produce a self-consistent (but different) chain.
  * **Signed receipt** — key-SIGNED proof. Binds verified work to payment under a
    signer's key; verified with that signer's address. Proves authorship, not just
    integrity. (Built elsewhere; not this file.)

Serialization is byte-stable (``sort_keys=True``, fixed ``separators``) so a chain
written by one process re-verifies bit-for-bit in another.

Conventions
-----------
* **Genesis** — the first entry's ``prev_hash`` is :data:`GENESIS_HASH`, the
  constant ``"0x" + "0" * 64``.
* **seq** — sequence numbers start at ``0`` for the genesis entry and increase by
  one per append. ``verify_chain`` requires them to be contiguous.
* **hash form** — every hash is ``"0x"`` followed by a sha256 hexdigest (lowercase).

Pure stdlib: ``json``, ``hashlib``, ``os``.
"""

from __future__ import annotations

import hashlib
import json
import os

from agent_exchange.payments.audit_types import LedgerEntry
from agent_exchange.redact import Policy, default_policy, redact_obj

# The genesis predecessor hash: 0x followed by 64 zero hex digits. The very first
# appended entry chains onto this constant instead of a real previous entry.
GENESIS_HASH = "0x" + "0" * 64


def _entry_hash(
    seq: int,
    timestamp: str,
    event: str,
    payload: dict,
    prev_hash: str,
) -> str:
    """Compute an entry's chained hash.

    ``"0x" + sha256`` hexdigest over the DETERMINISTIC canonical serialization of
    the entry's fields, including ``prev_hash`` (which is what links the chain).
    The serialization is fixed (``sort_keys=True``, ``separators=(",", ":")``) so
    the same logical entry hashes identically across processes and machines.
    """
    canonical = json.dumps(
        {
            "seq": seq,
            "timestamp": timestamp,
            "event": event,
            "payload": payload,
            "prev_hash": prev_hash,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return "0x" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _entry_to_json(entry: LedgerEntry) -> str:
    """Byte-stable one-line serialization of a stored row (field order fixed)."""
    return json.dumps(
        {
            "seq": entry.seq,
            "timestamp": entry.timestamp,
            "event": entry.event,
            "payload": entry.payload,
            "prev_hash": entry.prev_hash,
            "entry_hash": entry.entry_hash,
        },
        sort_keys=True,
        separators=(",", ":"),
    )


class HashChainedLedger:
    """Append-only, tamper-evident JSONL ledger of settlement-gate events.

    One :class:`LedgerEntry` per line. Appends use ``O_APPEND`` (a single atomic
    line write) so the log is never rewritten in place — mirroring the project's
    other append-only writer. The genesis entry has ``seq == 0`` and
    ``prev_hash == GENESIS_HASH``; each later entry's ``prev_hash`` is the prior
    entry's ``entry_hash``.
    """

    def __init__(self, path: str, *, redact_policy: Policy | None = None) -> None:
        self.path = path
        # Write-time PII redaction policy (default = conservative PII, default-ON).
        # The payload is redacted BEFORE the chained hash is computed, so the chain
        # remains tamper-evident over the REDACTED content — verify_chain() re-derives
        # the same hash from the persisted (redacted) payload and still passes.
        self.redact_policy: Policy = redact_policy if redact_policy is not None else default_policy()
        # Create the parent dir if needed; do NOT create/require the file itself.
        os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)

    def _tail(self) -> tuple[int, str]:
        """Return ``(last_seq, last_entry_hash)``, or ``(-1, GENESIS_HASH)`` if empty.

        ``last_seq == -1`` signals an empty ledger so the next append computes
        ``seq = -1 + 1 == 0`` for the genesis entry.
        """
        entries = self.entries()
        if not entries:
            return -1, GENESIS_HASH
        last = entries[-1]
        return last.seq, last.entry_hash

    def append(self, event: str, payload: dict, *, timestamp: str) -> LedgerEntry:
        """Append one event, chained onto the current tail, and return its entry.

        Reads the current tail's ``entry_hash`` (or :data:`GENESIS_HASH` if the
        ledger is empty), sets ``seq = last_seq + 1``, computes the chained
        ``entry_hash``, and atomically appends the row as one JSON line.
        """
        last_seq, prev_hash = self._tail()
        seq = last_seq + 1
        # Redact PII from the payload BEFORE hashing so the chain commits to (and the
        # file persists) only the redacted content; verify_chain() re-derives this hash.
        payload = redact_obj(payload, self.redact_policy)
        entry_hash = _entry_hash(seq, timestamp, event, payload, prev_hash)
        entry = LedgerEntry(
            seq=seq,
            timestamp=timestamp,
            event=event,
            payload=payload,
            prev_hash=prev_hash,
            entry_hash=entry_hash,
        )
        line = (_entry_to_json(entry) + "\n").encode("utf-8")
        fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
        try:
            os.write(fd, line)  # single atomic append of one line
        finally:
            os.close(fd)
        return entry

    def entries(self) -> list[LedgerEntry]:
        """Read every entry back, in file order. Empty list if the file is absent."""
        if not os.path.exists(self.path):
            return []
        out: list[LedgerEntry] = []
        with open(self.path, encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                row = json.loads(line)
                out.append(
                    LedgerEntry(
                        seq=row["seq"],
                        timestamp=row["timestamp"],
                        event=row["event"],
                        payload=row["payload"],
                        prev_hash=row["prev_hash"],
                        entry_hash=row["entry_hash"],
                    )
                )
        return out

    def verify_chain(self) -> bool:
        """Walk the chain and return True only if it is fully intact.

        For each entry, in order:
          * ``seq`` must be contiguous, starting at ``0``.
          * ``prev_hash`` must equal the previous entry's ``entry_hash``
            (:data:`GENESIS_HASH` for the first).
          * the stored ``entry_hash`` must RE-COMPUTE to the same value over the
            entry's fields (this is what makes a payload edit detectable).

        Any mismatch ⇒ False (tamper detected).
        """
        prev_hash = GENESIS_HASH
        for i, entry in enumerate(self.entries()):
            if entry.seq != i:
                return False
            if entry.prev_hash != prev_hash:
                return False
            recomputed = _entry_hash(
                entry.seq,
                entry.timestamp,
                entry.event,
                entry.payload,
                entry.prev_hash,
            )
            if recomputed != entry.entry_hash:
                return False
            prev_hash = entry.entry_hash
        return True


def tamper_check(path: str) -> bool:
    """Convenience: load the ledger at ``path`` and verify its chain.

    Returns True iff the chain is fully intact (no tampering detected).
    """
    return HashChainedLedger(path).verify_chain()
