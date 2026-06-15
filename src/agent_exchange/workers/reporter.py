"""The dedicated REPORTER role — consolidates a team's findings into one report.

A hired team audits a contract in a Band work room: each clause-area specialist
posts its own findings (in parallel), then the team hands off to a single
**reporter** agent. The reporter reads the whole room — every specialist's
findings plus the room's context — and synthesizes a consolidated deliverable: a
concise executive summary plus a deduplicated, prioritized list of the most
material claims.

Crucially, the reporter's claims are themselves graded by the verifier against the
contract, exactly like the specialists' findings — so the reporter is held to the
same grounding discipline: it may only restate/consolidate what is actually present
in the supplied contract and findings, never invent clauses or import outside legal
knowledge. A claim that cannot be confirmed against the contract text is worthless
by construction.

Public API:
  - `REPORTER_SYSTEM` / `REPORTER_PROMPT_VERSION` — the versioned synthesis prompt.
  - `ReporterWorker` — a `Reporter`-protocol-satisfying worker that wraps a
    `ModelBackend`; its `synthesize(contract, findings, room_context)` runs one
    model call and parses the result into a `ReportResult`.

Design notes (mirrors `SpecialistWorker`):
  - The backend (and therefore the model id) is injected, never constructed here.
  - `temperature=0.0` for determinism/auditability; the prompt does the steering.
  - Parsing is fail-safe: any non-conforming model output yields
    `ReportResult(summary="<unparseable>", claims=())` — the reporter NEVER raises,
    so a misbehaving model produces an empty (unpayable) report rather than a crash.
"""

from __future__ import annotations

import json
import re

from ..audit.room_audit_types import ReportResult, Reporter
from ..core import Message, ModelBackend
from .finding import Finding, _coerce_severity

# Mirror `finding.py`'s fence stripper so the reporter tolerates models that wrap
# their JSON in ```json ... ``` fences despite being told not to.
_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.IGNORECASE)

#: Sentinel summary returned when the model output can't be parsed into a report.
_UNPARSEABLE = "<unparseable>"


# ---------------------------------------------------------------------------
# Prompt engineering
# ---------------------------------------------------------------------------

REPORTER_PROMPT_VERSION = "reporter_v1"

REPORTER_SYSTEM = """You are the dedicated REPORTER for a team of contract-audit \
specialists. The specialists have each audited their own clause area of the CONTRACT \
below and posted their FINDINGS. Your single job is to CONSOLIDATE those findings into \
one report for the client.

Produce two things:
1. A concise EXECUTIVE SUMMARY (a few sentences) of the contract's most important \
risks, written for a decision-maker — what matters most and why.
2. A DEDUPLICATED, PRIORITIZED list of the most material CLAIMS, highest business risk \
first. Merge findings that make the same point (keep the clearest, most specific \
wording and the governing clause reference); drop trivial or redundant ones.

GROUNDING — this is non-negotiable, because your claims are verified against the \
CONTRACT text exactly like the specialists' were:
- Use ONLY the supplied CONTRACT and FINDINGS. Never use outside legal knowledge, never \
assume, never invent a clause that the contract does not contain.
- Every claim MUST be a single discrete, checkable assertion that a verifier can \
confirm or refute by reading the cited contract text. Prefer the contract's own \
wording; anchor each claim to its section number in `clause_ref`.
- DO NOT FABRICATE. If the findings overstate something the contract does not actually \
say, correct it down to what the text supports. A claim that cannot be confirmed \
against the contract is worthless.

OUTPUT — a single JSON OBJECT, and nothing else:
{"summary": "<executive summary>", "claims": [{"clause_ref": "<section number or '' \
if none>", "claim": "<one checkable assertion>", "severity": "low|medium|high"}, ...]}
- `severity` is the BUSINESS RISK of the term to the party it operates against: \
"high" = materially harmful / one-sided / unbounded exposure; "medium" = notable but \
bounded; "low" = minor or routine.
- One assertion per claim; split compound points into separate claims.
- Output ONLY the JSON object. No prose, no commentary, no markdown code fences."""


def _digest_room_context(room_context: list[dict]) -> str:
    """Condense the room context into a short, situational-awareness preamble.

    The reporter is grounded in the CONTRACT + FINDINGS, not the chatter — so the
    room context is offered only as lightweight situational awareness (who posted,
    what they said) and is kept compact. Each entry is rendered as one line, best
    effort; entries that aren't dict-shaped or carry no useful text are skipped.

    Args:
        room_context: The room's message log, each a loose dict (e.g.
            ``{"author"/"handle"/"name": ..., "text"/"content"/"message": ...}``).

    Returns:
        A newline-joined digest, or ``""`` when there's nothing usable.
    """
    lines: list[str] = []
    for entry in room_context or []:
        if not isinstance(entry, dict):
            continue
        author = (
            entry.get("author")
            or entry.get("handle")
            or entry.get("name")
            or entry.get("role")
            or "member"
        )
        text = entry.get("text") or entry.get("content") or entry.get("message") or ""
        text = str(text).strip()
        if not text:
            continue
        lines.append(f"- {str(author).strip()}: {text}")
    return "\n".join(lines)


def _format_findings(findings: list[Finding]) -> str:
    """Render the team's findings as a numbered, machine-legible list for the prompt.

    Each finding is shown with its source worker, clause reference, severity, and the
    checkable claim — everything the reporter needs to deduplicate and prioritize.

    Args:
        findings: The specialists' posted findings.

    Returns:
        A numbered list (one finding per line), or a clear marker when empty.
    """
    if not findings:
        return "(no findings were posted by the team)"
    lines: list[str] = []
    for i, f in enumerate(findings, 1):
        ref = f.clause_ref or "—"
        lines.append(
            f"{i}. [{f.worker}] (clause {ref}, severity {f.severity}) {f.claim}"
        )
    return "\n".join(lines)


def _build_user_message(
    contract: str, findings: list[Finding], room_context: list[dict]
) -> str:
    """Compose the reporter's user turn: contract, then findings, then optional digest.

    Args:
        contract: The full contract text (the verifier's ground truth).
        findings: The specialists' findings to consolidate.
        room_context: The room message log (offered as situational awareness only).

    Returns:
        The user message string.
    """
    parts = [
        "CONTRACT (ground truth):",
        '"""',
        contract.strip(),
        '"""',
        "",
        f"TEAM FINDINGS to consolidate ({len(findings)}):",
        _format_findings(findings),
    ]
    digest = _digest_room_context(room_context)
    if digest:
        parts += ["", "ROOM CONTEXT (for situational awareness only):", digest]
    parts += ["", "Return the consolidated report now as the JSON object."]
    return "\n".join(parts)


def _parse_report(text: str, reporter_name: str) -> ReportResult:
    """Parse a model completion into a `ReportResult`. Fail-safe — never raises.

    Mirrors `finding.parse_findings`' robustness (fence stripping + brace-bounded
    JSON extraction) but extracts a single top-level OBJECT (the report) rather than
    an array. On any failure — no JSON object found, invalid JSON, wrong shape, or a
    missing/empty summary — returns the sentinel
    ``ReportResult(summary="<unparseable>", claims=())`` so the caller can treat a
    botched report as "no report" rather than handling an exception.

    Args:
        text: The raw model completion.
        reporter_name: The reporter's name, stamped onto every claim's
            `Finding.worker` (so the report's claims are attributable to the reporter).

    Returns:
        The parsed report, or the unparseable sentinel.
    """
    unparseable = ReportResult(summary=_UNPARSEABLE, claims=())
    t = _FENCE_RE.sub("", (text or "").strip())
    start, end = t.find("{"), t.rfind("}")
    if start == -1 or end == -1 or end < start:
        return unparseable
    try:
        obj = json.loads(t[start : end + 1])
    except json.JSONDecodeError:
        return unparseable
    if not isinstance(obj, dict):
        return unparseable

    summary = str(obj.get("summary", "")).strip()
    if not summary:
        return unparseable

    raw_claims = obj.get("claims", [])
    if not isinstance(raw_claims, list):
        raw_claims = []
    claims: list[Finding] = []
    for it in raw_claims:
        if not isinstance(it, dict):
            continue
        claim = str(it.get("claim", "")).strip()
        if not claim:
            continue
        claims.append(
            Finding(
                worker=reporter_name,
                clause_ref=str(it.get("clause_ref", "") or "").strip(),
                claim=claim,
                severity=_coerce_severity(it.get("severity")),
            )
        )
    return ReportResult(summary=summary, claims=tuple(claims))


# ---------------------------------------------------------------------------
# Worker
# ---------------------------------------------------------------------------


class ReporterWorker:
    """The dedicated reporter agent that consolidates a team's findings.

    Satisfies the `Reporter` protocol (`async synthesize(contract, findings,
    room_context)`), so the orchestrator can hand the room off to it after the
    specialists have posted. One `synthesize` call == one model call.

    Attributes:
        backend: The `ModelBackend` used to run the synthesis. Injected (never
            constructed here) so the same reporter works against a real provider or a
            `MockBackend` in tests.
        name: Stable identifier for this reporter. Stamped onto every claim's
            `Finding.worker`, so the report's consolidated claims are attributable
            (and payable) to the reporter rather than to any specialist.
    """

    def __init__(self, backend: ModelBackend, *, name: str = "reporter") -> None:
        self.backend = backend
        self.name = name

    async def synthesize(
        self, contract: str, findings: list[Finding], room_context: list[dict]
    ) -> ReportResult:
        """Consolidate the room's findings into one verifiable report.

        Sends ``[REPORTER_SYSTEM, contract + findings + context digest]`` to the
        backend at ``temperature=0.0`` and parses the completion into a
        `ReportResult`. Fail-safe by construction: any non-conforming output yields
        ``ReportResult(summary="<unparseable>", claims=())`` — this method NEVER
        raises, so a misbehaving model produces an empty (unpayable) report rather
        than crashing the room.

        Args:
            contract: The full contract text — the verifier's ground truth.
            findings: The specialists' posted findings to consolidate.
            room_context: The room message log, used only for situational awareness.

        Returns:
            The reporter's `ReportResult`: an executive summary plus the consolidated,
            verifiable claims (each a `Finding` stamped with ``worker == self.name``).
            May be the unparseable sentinel on parse failure.
        """
        messages = [
            Message.system(REPORTER_SYSTEM),
            Message.user(_build_user_message(contract, findings, room_context)),
        ]
        result = await self.backend.complete(messages, temperature=0.0, max_tokens=2000)
        return _parse_report(result.text, self.name)


# A static check that the worker honours the protocol (no runtime cost; mypy-visible).
_: type[Reporter] = ReporterWorker
