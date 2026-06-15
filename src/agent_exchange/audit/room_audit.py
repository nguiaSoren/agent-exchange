"""In-room team collaboration orchestrator — the work-room audit.

The hired team does the audit IN the Band work room: each member audits its clause
area in parallel and POSTS its findings into the shared room as itself; the team then
hands off — via an @mention — to a dedicated REPORTER agent that reads the room and
synthesizes a consolidated report, which it posts back. Both layers are then graded by
the `Verifier` against the contract:

  * every specialist finding's `claim`, and
  * every claim in the reporter's synthesis,

are verified against the contract text — the shared room is the verifier's ground truth.

This mirrors the linear `audit()` pipeline's deliver → verify seam
(`claims = [f.claim for f in findings]; verdicts = verifier.verify(contract, claims);
audited = zip(findings, verdicts)`) but spread across two layers (specialists + reporter)
and grounded in a real Band room.

Robustness contract (mirroring the bounded-fan-out pool):

  * **Bounded fan-out** — specialist audits run concurrently under an
    `asyncio.Semaphore(max_concurrency)` so a large team cannot cascade-429 the
    underlying providers.
  * **Fail-safe per member** — a member whose auditor raises contributes zero findings
    and is logged at WARNING; it never aborts the round.
  * **Deterministic order** — collected findings are ordered by member specialty, and
    each member's own findings preserve their emitted order.
  * **Best-effort Band I/O** — every room post is wrapped so a failed post can never lose
    the findings or their verification. All Band I/O is kept at the boundary, so the
    orchestrator runs offline against an in-memory Band fake + a mock model backend.
"""

from __future__ import annotations

import asyncio
import logging

from ..verify.verifier import Verifier
from ..workers.finding import Finding
from .report import AuditedFinding
from .room_audit_types import (
    CollaborationMember,
    ReporterMember,
    RoomAuditResult,
)

__all__ = ["collaborate_in_room"]

_log = logging.getLogger(__name__)


def _format_findings_post(specialty: str, findings: list[Finding]) -> str:
    """Render a member's findings into a readable in-room post.

    Format::

        [{specialty}] {n} findings:
        - {clause_ref}: {claim} ({severity})
        - ...

    A member with no findings posts an explicit "0 findings" line so the room (and the
    reporter reading it) sees that the area was covered and came back clean.
    """
    header = f"[{specialty}] {len(findings)} findings:"
    if not findings:
        return header
    lines = [
        f"- {f.clause_ref or '(no clause)'}: {f.claim} ({f.severity})"
        for f in findings
    ]
    return "\n".join([header, *lines])


async def _best_effort_post(
    band, room_id: str, content: str, mentions: list[dict], *, what: str
) -> None:
    """Post into the room, containing any failure.

    A post is informational: the findings and their verification are the deliverable, so a
    transient Band error must NOT abort the round or lose work. Failures are logged at
    WARNING and swallowed.
    """
    try:
        await band.post_message(room_id, content, mentions=mentions)
    except Exception as exc:  # noqa: BLE001 — intentional: contain + record, never lose findings.
        _log.warning("in-room %s post failed (continuing): %s", what, exc, exc_info=True)


async def _member_round(
    member: CollaborationMember,
    contract: str,
    room_id: str,
    sem: asyncio.Semaphore,
    reporter_mention: dict,
) -> list[Finding]:
    """Run one member's audit under the concurrency gate and post its findings as itself.

    A member whose auditor raises contributes zero findings (logged at WARNING) and never
    aborts the round. The findings post is best-effort and @mentions the reporter (Band
    requires every message to mention at least one participant; the findings are headed to
    the reporter for synthesis anyway).
    """
    async with sem:
        try:
            findings = list(await member.auditor.findings(contract) or [])
        except Exception as exc:  # noqa: BLE001 — contain a failing member; round continues.
            _log.warning(
                "member %r auditor failed during in-room audit; treating as 0 findings: %s",
                member.specialty,
                exc,
                exc_info=True,
            )
            return []
        await _best_effort_post(
            member.band,
            room_id,
            _format_findings_post(member.specialty, findings),
            mentions=[reporter_mention],
            what=f"findings ({member.specialty})",
        )
        return findings


async def collaborate_in_room(
    work_room_id: str,
    contract: str,
    team: list[CollaborationMember],
    reporter_member: ReporterMember,
    verifier: Verifier,
    *,
    max_concurrency: int = 6,
) -> RoomAuditResult:
    """Run an in-room collaborative audit: parallel specialists → reporter → verify both.

    Flow:

    1. **Parallel audit** (bounded by ``asyncio.Semaphore(max_concurrency)``): every
       ``member`` audits the contract and posts a readable summary of its findings into the
       room *as itself*. A member that raises contributes zero findings (logged) and never
       aborts the round. Collected findings are ordered by member specialty, with each
       member's own order preserved.
    2. **Handoff**: one message is posted into the room @mentioning the reporter, asking it
       to synthesize. The team posts this (first member's band); if the team is empty the
       handoff is skipped, and if no member band is available the reporter's own band is the
       fallback poster.
    3. **Reporter synthesis**: the reporter reads the room context and synthesizes a
       consolidated ``ReportResult``, then posts its summary back into the room as itself.
    4. **Verify both layers**: every specialist finding's ``claim`` and every claim in the
       reporter's synthesis are graded by ``verifier`` against ``contract``. Each layer's
       findings are zipped with their verdicts into ``AuditedFinding`` tuples (the verifier
       contract is one verdict per claim, in order; an empty claim set verifies to an empty
       tuple cleanly).

    Parameters
    ----------
    work_room_id:
        The Band work room the team collaborates in (the verifier's ground truth context).
    contract:
        The full contract text every member audits and every claim is graded against.
    team:
        The hired specialists, each with its own Band client and auditor brain. May be empty
        (then there are no specialist findings and the handoff is skipped).
    reporter_member:
        The dedicated reporter: its own Band client, its synthesis brain, and the @mention
        the team hands off to.
    verifier:
        Grades claims against the contract; ``verify(contract, claims)`` returns one verdict
        per claim, in order.
    max_concurrency:
        Upper bound on concurrently-running member audits (caps provider fan-out).

    Returns
    -------
    RoomAuditResult
        ``work_room_id``; the specialists' ``audited`` findings+verdicts; the reporter's
        ``report_summary``; and the reporter's ``report_audited`` claims+verdicts.
    """
    sem = asyncio.Semaphore(max_concurrency)

    # Collect each member's mention payload (one me() per member). Band requires every
    # message to @mention at least one participant, so the reporter's summary post is
    # addressed to the team; the members' findings posts are addressed to the reporter.
    team_mentions: list[dict] = []
    for member in team:
        try:
            me = await member.band.me()
            team_mentions.append(
                {"id": me["id"], "handle": me.get("handle", ""), "name": me.get("name", member.specialty)}
            )
        except Exception as exc:  # noqa: BLE001 — a missing identity just drops one mention target.
            _log.warning("could not resolve identity for member %r: %s", member.specialty, exc)

    # 1. PARALLEL AUDIT — each member audits + posts its findings as itself, concurrently.
    #    Pair each member with its roster index so equal-specialty members keep a stable,
    #    reproducible order after sorting (deterministic assembly despite concurrent work).
    indexed = list(enumerate(team))
    results = await asyncio.gather(
        *(
            _member_round(member, contract, work_room_id, sem, reporter_member.mention)
            for _, member in indexed
        )
    )

    # Deterministic assembly: order by (specialty, original index); each member's own
    # findings keep their emitted order.
    ordered = sorted(
        zip(indexed, results),
        key=lambda pair: (pair[0][1].specialty, pair[0][0]),
    )
    all_findings: list[Finding] = []
    for _, findings in ordered:
        all_findings.extend(findings)

    # 2. HANDOFF — the team @mentions the reporter to synthesize. The market/team posts it
    #    (first member's band); fall back to the reporter's own band if the team is empty
    #    or has no usable band.
    reporter_name = reporter_member.mention.get("name") or reporter_member.mention.get(
        "handle", "reporter"
    )
    handoff_band = team[0].band if team else reporter_member.band
    if handoff_band is not None:
        await _best_effort_post(
            handoff_band,
            work_room_id,
            f"@{reporter_name} please synthesize the team's findings.",
            mentions=[reporter_member.mention],
            what="handoff",
        )

    # 3. REPORTER SYNTHESIS — read the room, synthesize, post the summary back as the reporter.
    #    Reading the room is best-effort: if it fails, the reporter still synthesizes from the
    #    findings it was handed (empty room context), so a Band read can't lose the report.
    try:
        room_context = await reporter_member.band.get_context(work_room_id)
    except Exception as exc:  # noqa: BLE001 — contain a failed room read; synthesize anyway.
        _log.warning(
            "reading room context failed (continuing with empty context): %s",
            exc,
            exc_info=True,
        )
        room_context = []

    report = await reporter_member.reporter.synthesize(contract, all_findings, room_context)
    # The reporter delivers its summary back to the team (Band requires ≥1 mention).
    summary_mentions = team_mentions or [reporter_member.mention]
    await _best_effort_post(
        reporter_member.band,
        work_room_id,
        report.summary,
        mentions=summary_mentions,
        what="report summary",
    )

    # 4. VERIFY BOTH LAYERS — specialists' findings AND the reporter's claims, each graded
    #    against the contract. One verdict per claim, in order (empty claim set → []).
    finding_verdicts = await verifier.verify(
        contract, [f.claim for f in all_findings]
    )
    audited = tuple(
        AuditedFinding(f, v) for f, v in zip(all_findings, finding_verdicts)
    )

    report_claims = list(report.claims)
    if report_claims:
        report_verdicts = await verifier.verify(
            contract, [c.claim for c in report_claims]
        )
        report_audited = tuple(
            AuditedFinding(c, v) for c, v in zip(report_claims, report_verdicts)
        )
    else:
        report_audited = ()

    # 5. The full in-room deliverable: both layers, graded.
    return RoomAuditResult(
        work_room_id=work_room_id,
        audited=audited,
        report_summary=report.summary,
        report_audited=report_audited,
    )
