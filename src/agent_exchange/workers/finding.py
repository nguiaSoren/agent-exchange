"""Finding schema + parser + the Specialist interface — the worker-pool contract.

A worker (a clause-audit specialist) reads a contract and emits structured
**findings**, each a checkable assertion the verifier can grade. This module is the
locked contract every pool piece builds against:
  - `Finding` — {worker, clause_ref, claim, severity}; `claim` is what the verifier grades.
  - `parse_findings(text, worker)` — robust JSON parse, fail-soft (garbage → [] → nothing
    to pay for; a junk worker simply produces no payable findings).
  - `Specialist` — the async interface a pool fans out over (`.name`, `findings(contract)`).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Literal, Protocol, runtime_checkable

Severity = Literal["low", "medium", "high"]
_VALID_SEV = ("low", "medium", "high")
_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class Finding:
    """One structured finding from a specialist. `claim` is the verifier's input."""

    worker: str          # which specialist produced it
    clause_ref: str      # e.g. "7.1" / "Section 9.3" / "" if none cited
    claim: str           # the checkable assertion about the contract
    severity: Severity = "medium"

    def __post_init__(self) -> None:
        if not self.claim.strip():
            raise ValueError("Finding.claim must be non-empty")
        if self.severity not in _VALID_SEV:
            raise ValueError(f"severity must be one of {_VALID_SEV}, got {self.severity!r}")


def _coerce_severity(raw: object) -> Severity:
    s = str(raw or "medium").strip().lower()
    if s in _VALID_SEV:
        return s  # type: ignore[return-value]
    if s.startswith("hi"):
        return "high"
    if s.startswith("lo"):
        return "low"
    return "medium"


def parse_findings(text: str, worker: str) -> list[Finding]:
    """Parse a model completion into findings. Fail-soft: a worker that emits
    no valid JSON / junk yields `[]` (safe — no findings means nothing to pay for)."""
    t = _FENCE_RE.sub("", (text or "").strip())
    start, end = t.find("["), t.rfind("]")
    if start == -1 or end == -1 or end < start:
        return []
    try:
        items = json.loads(t[start : end + 1])
    except json.JSONDecodeError:
        return []
    if not isinstance(items, list):
        return []
    out: list[Finding] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        claim = str(it.get("claim", "")).strip()
        if not claim:
            continue
        out.append(
            Finding(
                worker=worker,
                clause_ref=str(it.get("clause_ref", "") or "").strip(),
                claim=claim,
                severity=_coerce_severity(it.get("severity")),
            )
        )
    return out


@runtime_checkable
class Specialist(Protocol):
    """A clause-audit specialist a pool fans out over."""

    name: str

    async def findings(self, contract: str) -> list[Finding]: ...
