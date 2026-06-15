"""Locked types for in-room team collaboration (the work-room audit).

The hired team works IN the Band work room: each member audits its clause area and
posts its findings (parallel), then hands off — via an @mention — to a dedicated
REPORTER agent that reads the room and synthesizes a consolidated report. The room's
findings AND the reporter's synthesis are both graded by the verifier against the
contract — the shared room context is the verifier's ground truth.

These frozen types are the seam the reporter role, the orchestrator, and the tests
all code against, so they can be built in parallel.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from ..band.client import BandClient
from ..workers.finding import Finding
from .report import AuditedFinding


@runtime_checkable
class Auditor(Protocol):
    """Anything that audits a contract into findings (e.g. ``SpecialistWorker``,
    whose method is ``findings(contract) -> list[Finding]``)."""

    async def findings(self, contract: str) -> list[Finding]: ...


@dataclass(frozen=True, slots=True)
class CollaborationMember:
    """One hired team member working in the room: its identity, its OWN Band client
    (so it posts as itself), and its auditor brain."""

    specialty: str
    area: str
    band: BandClient
    auditor: Auditor


@dataclass(frozen=True, slots=True)
class ReportResult:
    """The reporter's synthesis: a human-readable summary + its consolidated,
    verifiable claims (as `Finding`s the verifier can grade)."""

    summary: str
    claims: tuple[Finding, ...]


@runtime_checkable
class Reporter(Protocol):
    """The dedicated reporter brain: reads the room's findings + context, synthesizes."""

    async def synthesize(
        self, contract: str, findings: list[Finding], room_context: list[dict]
    ) -> ReportResult: ...


@dataclass(frozen=True, slots=True)
class ReporterMember:
    """The reporter agent: its own Band client, its synthesis brain, and the @mention
    payload the team hands off to."""

    band: BandClient
    reporter: Reporter
    mention: dict  # {id, handle, name}


@dataclass(frozen=True, slots=True)
class RoomAuditResult:
    """Outcome of in-room collaboration: every specialist finding graded + the
    reporter's synthesis graded, both against the contract."""

    work_room_id: str
    audited: tuple[AuditedFinding, ...]          # specialists' findings + verdicts
    report_summary: str
    report_audited: tuple[AuditedFinding, ...]   # reporter's consolidated claims + verdicts

    @property
    def all_audited(self) -> tuple[AuditedFinding, ...]:
        """Specialist findings + reporter claims, both graded — the full deliverable."""
        return self.audited + self.report_audited
