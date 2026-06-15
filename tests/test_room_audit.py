"""In-room team-collaboration tests — the work-room audit, proven OFFLINE.

`collaborate_in_room` is the team's on-network workflow made testable with ZERO
network: a hired team works IN a Band work room (here a set of `FakeBandClient`s
sharing one `BandWorld`), and a `Verifier` on a `MockBackend` grades the work.

The flow under test (per room_audit_types.py + room_audit.py):
  1. PARALLEL — each `CollaborationMember`'s auditor audits the contract and POSTS a
     finding summary into the room as itself.
  2. HANDOFF — an @mention message hands the room off to the `ReporterMember`.
  3. SYNTHESIS — the reporter reads the room, synthesizes a `ReportResult`, posts it.
  4. VERIFY — both the specialists' findings AND the reporter's claims are graded
     against the contract (the shared room is the verifier's ground truth).
  5. RESULT — a `RoomAuditResult`: `audited` (specialist findings + verdicts),
     `report_audited` (reporter claims + verdicts), `all_audited` = both.

The crafted scenario is the headline claim made concrete inside a room: a true
finding is CONFIRMED, a fabricated finding (a clause absent from the contract) is
caught UNSUPPORTED, and the reporter's two consolidated claims are graded the same
way — caught + unpayable — with no live model in the loop.

Robustness: a member whose auditor RAISES contributes zero findings, but the round
still completes and the surviving member + the reporter are still verified.

Verdict alignment: the `Verifier` returns verdicts IN ORDER of the claims it is
handed, and `collaborate_in_room` runs TWO verify passes (specialist findings, then
reporter claims) whose claim sets + orders are an internal detail. So instead of a
fixed reply array (which would require us to pin that ordering) we use a
CONTENT-KEYED MockBackend: it reads the claims out of the verifier's own user prompt
and emits the matching verdict per claim, in whatever order it was asked — robust to
the orchestrator's internal ordering while still fully deterministic + offline.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from agent_exchange.audit.report import AuditedFinding
from agent_exchange.audit.room_audit import collaborate_in_room
from agent_exchange.audit.room_audit_types import (
    CollaborationMember,
    ReporterMember,
    ReportResult,
    RoomAuditResult,
)
from agent_exchange.band.client import BandWorld, FakeBandClient
from agent_exchange.core import CompletionResult, MockBackend, Usage
from agent_exchange.verify import Verdict, Verifier
from agent_exchange.workers.finding import Finding

CONTRACT = """\
1. Liability. Vendor's aggregate liability shall not exceed the fees paid in the prior 12 months.
2. Termination. Either party may terminate for convenience on 30 days' written notice.
3. Confidentiality. Each party shall protect the other's confidential information for 3 years.
"""

# ── the crafted claims (the verifier keys verdicts off these exact strings) ──

# Specialist findings: one TRUE (clause 1, real), one FABRICATED (clause 9.4 is absent).
TRUE_CLAIM = "liability is capped at the prior 12 months' fees"
FAB_CLAIM = "clause 9.4 grants the vendor unlimited indemnity"

# The reporter's consolidated claims: one TRUE (restates clause 2), one FABRICATED.
REPORT_TRUE_CLAIM = "either party may terminate for convenience on 30 days' notice"
REPORT_FAB_CLAIM = "clause 12 awards the vendor a perpetual royalty"

# claim text → (verdict, confidence, evidence_quote) — the ground-truth grade book.
_GRADES: dict[str, tuple[str, float, str | None]] = {
    TRUE_CLAIM: (
        "confirmed",
        0.96,
        "Vendor's aggregate liability shall not exceed the fees paid in the prior 12 months.",
    ),
    FAB_CLAIM: ("unsupported", 0.93, None),
    REPORT_TRUE_CLAIM: (
        "confirmed",
        0.94,
        "Either party may terminate for convenience on 30 days' written notice.",
    ),
    REPORT_FAB_CLAIM: ("unsupported", 0.9, None),
}


class _KeyedVerifierBackend(MockBackend):
    """A deterministic, networkless verifier backend that grades by claim CONTENT.

    The verifier embeds its claims, in order, into the user turn (one numbered line
    per claim). This backend recovers that order from the prompt and emits the
    crafted verdict for each claim from `_GRADES`, so the reply lines up 1:1 with the
    claims regardless of how `collaborate_in_room` ordered them. A claim it doesn't
    recognise fails safe to `unsupported` (never a silent confirm)."""

    async def complete(self, messages, *, temperature=0.0, max_tokens=None) -> CompletionResult:
        user_text = next((m.content for m in messages if m.role == "user"), "")
        # The verifier requires verdicts in the SAME ORDER as its numbered claim list,
        # so order the matched claims by where each first appears in the prompt — not by
        # _GRADES insertion order (which need not match the orchestrator's claim order).
        ordered = sorted(
            (c for c in _GRADES if c in user_text), key=user_text.find
        )
        reply = json.dumps(
            [
                {
                    "verdict": _GRADES[c][0],
                    "confidence": _GRADES[c][1],
                    "reason": f"graded {c!r}",
                    "evidence_quote": _GRADES[c][2],
                }
                for c in ordered
            ]
        )
        in_tok = sum(len(m.content) for m in messages) // 4
        out_tok = max(1, len(reply) // 4)
        return CompletionResult(
            text=reply,
            model="mock-1",
            provider="mock",
            usage=Usage(in_tok, out_tok, in_tok + out_tok, estimated_cost_usd=0.0),
            submission_ns=0,
            return_ns=1,
            finish_reason="stop",
        )


# ── stub auditors / reporter (implement the Protocols, zero network) ──


class _StubAuditor:
    """Canned-findings auditor (satisfies the `Auditor` protocol)."""

    def __init__(self, findings: list[Finding]) -> None:
        self._findings = findings

    async def findings(self, contract: str) -> list[Finding]:
        return list(self._findings)


class _RaisingAuditor:
    """An auditor that blows up inside `findings` — must be contained by the room."""

    async def findings(self, contract: str) -> list[Finding]:
        raise RuntimeError("simulated auditor failure")


class _StubReporter:
    """Returns a canned `ReportResult` (satisfies the `Reporter` protocol)."""

    def __init__(self, result: ReportResult) -> None:
        self._result = result

    async def synthesize(self, contract, findings, room_context) -> ReportResult:
        return self._result


REPORT = ReportResult(
    summary="Liability is capped at 12 months' fees; either party may terminate on 30 days' notice.",
    claims=(
        Finding(worker="reporter", clause_ref="2", claim=REPORT_TRUE_CLAIM, severity="medium"),
        Finding(worker="reporter", clause_ref="12", claim=REPORT_FAB_CLAIM, severity="high"),
    ),
)


def _build_world() -> tuple[BandWorld, str, list[CollaborationMember], ReporterMember, Verifier]:
    """A shared world + work room + two members + a reporter + a keyed verifier."""
    world = BandWorld()

    # The market creates the work room and adds every member as a participant.
    market = FakeBandClient("market", "market", "Market", world)

    liability = CollaborationMember(
        specialty="liability",
        area="liability caps and disclaimers",
        band=FakeBandClient("liability-bot", "liability-bot", "Liability Bot", world),
        auditor=_StubAuditor(
            [Finding(worker="liability", clause_ref="1", claim=TRUE_CLAIM, severity="high")]
        ),
    )
    indemnity = CollaborationMember(
        specialty="indemnity",
        area="indemnification obligations",
        band=FakeBandClient("indemnity-bot", "indemnity-bot", "Indemnity Bot", world),
        # The SEEDED LIAR: a finding citing a clause (9.4) absent from the contract.
        auditor=_StubAuditor(
            [Finding(worker="indemnity", clause_ref="9.4", claim=FAB_CLAIM, severity="high")]
        ),
    )
    team = [liability, indemnity]

    reporter_band = FakeBandClient("reporter-bot", "reporter-bot", "Reporter Bot", world)
    reporter_member = ReporterMember(
        band=reporter_band,
        reporter=_StubReporter(REPORT),
        mention={"id": "reporter-bot", "handle": "reporter-bot", "name": "Reporter Bot"},
    )

    async def _setup() -> str:
        rid = await market.create_room("Audit work room")
        for m in team:
            await market.add_participant(rid, m.band.agent_id)
        await market.add_participant(rid, reporter_band.agent_id)
        return rid

    room_id = asyncio.run(_setup())

    verifier = Verifier(_KeyedVerifierBackend())
    return world, room_id, team, reporter_member, verifier


def _collaborate() -> tuple[BandWorld, str, RoomAuditResult]:
    world, room_id, team, reporter_member, verifier = _build_world()
    result = asyncio.run(
        collaborate_in_room(room_id, CONTRACT, team, reporter_member, verifier)
    )
    return world, room_id, result


def _messages(world: BandWorld, room_id: str) -> list[dict]:
    return world.rooms[room_id]["messages"]


# ── result shape ──


def test_returns_room_audit_result_for_the_work_room():
    _world, room_id, result = _collaborate()
    assert isinstance(result, RoomAuditResult)
    assert result.work_room_id == room_id
    assert result.report_summary == REPORT.summary


# ── each member POSTED its finding into the work room ──


def test_each_member_posts_its_findings_into_the_room():
    world, room_id, _result = _collaborate()
    msgs = _messages(world, room_id)
    # Every member posted at least one message AS ITSELF (its own sender_id).
    senders = {m["sender_id"] for m in msgs}
    assert "liability-bot" in senders
    assert "indemnity-bot" in senders
    # The finding content actually reached the room (not just an empty ping).
    blob = "\n".join(m["content"] for m in msgs)
    assert TRUE_CLAIM in blob
    assert FAB_CLAIM in blob


# ── the @mention handoff to the reporter exists ──


def test_handoff_message_mentions_the_reporter():
    world, room_id, _result = _collaborate()
    msgs = _messages(world, room_id)
    # Some message routes to the reporter (its id is in the message's mentions),
    # and it was NOT posted by the reporter itself — it's a handoff TO the reporter.
    handoffs = [
        m for m in msgs
        if "reporter-bot" in m["_mention_ids"] and m["sender_id"] != "reporter-bot"
    ]
    assert handoffs, "expected an @mention handoff routed to the reporter"


# ── the reporter's synthesis was posted ──


def test_reporter_posts_its_summary():
    world, room_id, _result = _collaborate()
    msgs = _messages(world, room_id)
    reporter_msgs = [m for m in msgs if m["sender_id"] == "reporter-bot"]
    assert reporter_msgs, "expected the reporter to post into the room"
    assert any(REPORT.summary in m["content"] for m in reporter_msgs)


# ── audited: every specialist finding graded (confirmed vs unsupported) ──


def test_specialist_findings_are_graded():
    _world, _room_id, result = _collaborate()
    assert all(isinstance(af, AuditedFinding) for af in result.audited)
    by_claim = {af.finding.claim: af.verdict.verdict for af in result.audited}
    assert by_claim[TRUE_CLAIM] is Verdict.CONFIRMED       # the real finding → confirmed
    assert by_claim[FAB_CLAIM] is Verdict.UNSUPPORTED      # the fabricated finding → caught
    # exactly the two member findings, each graded once
    assert len(result.audited) == 2


# ── report_audited: the reporter's consolidated claims graded ──


def test_reporter_claims_are_graded():
    _world, _room_id, result = _collaborate()
    assert all(isinstance(af, AuditedFinding) for af in result.report_audited)
    by_claim = {af.finding.claim: af.verdict.verdict for af in result.report_audited}
    assert by_claim[REPORT_TRUE_CLAIM] is Verdict.CONFIRMED
    assert by_claim[REPORT_FAB_CLAIM] is Verdict.UNSUPPORTED   # reporter held to the same discipline
    assert len(result.report_audited) == 2


# ── all_audited == specialists + reporter, both graded ──


def test_all_audited_is_specialists_plus_reporter():
    _world, _room_id, result = _collaborate()
    assert result.all_audited == result.audited + result.report_audited
    assert len(result.all_audited) == 4
    # The headline invariant: the two fabricated claims were caught, across both layers.
    n_unsupported = sum(
        af.verdict.verdict is Verdict.UNSUPPORTED for af in result.all_audited
    )
    assert n_unsupported == 2


# ── robustness: a raising auditor contributes nothing, the round still completes ──


def test_raising_auditor_is_contained_round_still_verifies():
    # The orchestrator logs the contained failure (with a traceback) at WARNING — that
    # is the behaviour under test, so quiet it here to keep the test output clean.
    logging.getLogger("agent_exchange.audit.room_audit").setLevel(logging.ERROR)
    world = BandWorld()
    market = FakeBandClient("market", "market", "Market", world)

    good = CollaborationMember(
        specialty="liability",
        area="liability caps",
        band=FakeBandClient("liability-bot", "liability-bot", "Liability Bot", world),
        auditor=_StubAuditor(
            [Finding(worker="liability", clause_ref="1", claim=TRUE_CLAIM, severity="high")]
        ),
    )
    broken = CollaborationMember(
        specialty="indemnity",
        area="indemnification",
        band=FakeBandClient("indemnity-bot", "indemnity-bot", "Indemnity Bot", world),
        auditor=_RaisingAuditor(),
    )
    reporter_band = FakeBandClient("reporter-bot", "reporter-bot", "Reporter Bot", world)
    reporter_member = ReporterMember(
        band=reporter_band,
        reporter=_StubReporter(REPORT),
        mention={"id": "reporter-bot", "handle": "reporter-bot", "name": "Reporter Bot"},
    )

    room_id = asyncio.run(market.create_room("Audit work room"))
    asyncio.run(market.add_participant(room_id, good.band.agent_id))
    asyncio.run(market.add_participant(room_id, broken.band.agent_id))
    asyncio.run(market.add_participant(room_id, reporter_band.agent_id))

    verifier = Verifier(_KeyedVerifierBackend())
    result = asyncio.run(
        collaborate_in_room(room_id, CONTRACT, [good, broken], reporter_member, verifier)
    )

    # The broken member contributed ZERO findings; only the good member's survived.
    assert isinstance(result, RoomAuditResult)
    assert [af.finding.claim for af in result.audited] == [TRUE_CLAIM]
    assert result.audited[0].verdict.verdict is Verdict.CONFIRMED
    # The reporter still ran + was verified despite the mid-team failure.
    assert len(result.report_audited) == 2
    # The broken auditor never posted a finding into the room.
    senders = {m["sender_id"] for m in _messages(world, room_id)}
    assert "indemnity-bot" not in senders or all(
        FAB_CLAIM not in m["content"]
        for m in _messages(world, room_id)
        if m["sender_id"] == "indemnity-bot"
    )


def _run_all():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"  ✓ {fn.__name__}")
    print(f"\n{len(fns)} passed")


if __name__ == "__main__":
    _run_all()
