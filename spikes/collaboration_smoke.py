"""LIVE in-room collaboration smoke — run one full work-room audit through real Band.

This is the on-network end-to-end counterpart to `tests/test_room_audit.py` (which
proves the same flow OFFLINE on `FakeBandClient`s). It extends
`spikes/discovery_recruiting_smoke.py` one beat further: instead of stopping at a
recruited team, it has the hired team actually WORK in the Band work room —

  1. each member's real `SpecialistWorker` audits the contract and POSTS its findings
     into the room (in parallel), as itself;
  2. the team hands off to a dedicated REPORTER agent via an @mention;
  3. the reporter (a real `ReporterWorker`) reads the room + synthesizes a
     consolidated report and posts it;
  4. the verifier grades BOTH the specialists' findings AND the reporter's claims
     against the contract — the shared room is the ground truth.

It is NOT run by the test suite — the orchestrator runs it by hand when live Band
keys + a model provider are configured:

    python3 spikes/collaboration_smoke.py

Env contract (read from `.env`):
  - `BAND_SPECIALIST_<NAME>_KEY` — at least one specialist's Band key (the team).
    With NONE set it prints a registration hint and exits cleanly (never spends).
  - `BAND_REPORTER_KEY` — the reporter agent's own Band key. Falls back to
    `BAND_MARKET_KEY` if unset (so the reporter still has a distinct-or-shared identity).
  - `BAND_MARKET_KEY` — the market identity that CREATES the work room + adds members.
    Falls back to any specialist key.
  - `OPENAI_API_KEY` (+ optional `OPENAI_MODEL`, default gpt-4.1-mini) — the brain the
    specialists + reporter + verifier all run on.
  - Optional cross-owner tax bot: `BAND_AGENT_OWNER2_KEY` + `BAND_OWNER2_TAX_HANDLE`
    add a second-account tax specialist to the team (a real contact handshake is NOT
    performed here — that is `cross_owner_smoke.py`'s job; here the bot must already be
    addable, i.e. same room participation works once added by id).

Never crashes, never spends without keys.
"""

from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import httpx
from dotenv import load_dotenv

from agent_exchange.audit.room_audit import collaborate_in_room
from agent_exchange.audit.room_audit_types import CollaborationMember, ReporterMember
from agent_exchange.band.http_client import make_http_band_client, specialist_band_keys
from agent_exchange.core import make_backend
from agent_exchange.verify import Verdict, Verifier
from agent_exchange.workers.reporter import ReporterWorker
from agent_exchange.workers.specialist import SPECIALISTS, SpecialistWorker

# Explicit path (load_dotenv() with no path can fail depending on cwd). Env is read
# lazily by make_backend at call time, so loading it after the imports is fine.
load_dotenv("/Users/soren/Desktop/BAND HACKATHON/agent-exchange/.env")

# Map specialty name → (area, system_prompt) so we can build a real SpecialistWorker
# for whichever specialties we hold a Band key for.
_SPEC_META: dict[str, tuple[str, str]] = {
    name: (area, prompt) for name, area, prompt in SPECIALISTS
}

# A small but realistic ~8-clause MSA — enough surface for each specialist to probe.
SAMPLE_MSA = """\
MASTER SERVICES AGREEMENT

1. Liability. Vendor's aggregate liability under this Agreement is capped at the fees \
paid by Client in the twelve (12) months preceding the claim. This cap does not apply \
to breaches of confidentiality or indemnification obligations.

2. Intellectual Property. All work product, deliverables, and foreground IP created \
under this Agreement are assigned to Client upon creation. Vendor retains its \
pre-existing background IP and grants Client a non-exclusive license to use it.

3. Taxes. Fees are stated exclusive of tax. Client bears all sales, use, and VAT/GST. \
Each party is responsible for its own income and franchise taxes. Client shall gross \
up any withholding so Vendor receives the full invoiced amount.

4. Termination. Either party may terminate for cause on 30 days' written notice with a \
30-day cure period. Client may terminate for convenience on 60 days' notice. The \
initial term is 12 months and auto-renews for successive 12-month terms unless either \
party gives 30 days' notice of non-renewal.

5. Confidentiality & Data. Each party shall protect the other's Confidential \
Information for 3 years after disclosure. Vendor may not use Client data to train \
models. Vendor shall notify Client of any security breach within 72 hours.

6. Indemnification. Vendor shall indemnify Client against third-party claims that the \
deliverables infringe IP rights, including defense costs and settlements. This \
indemnity is expressly excluded from the liability cap in Clause 1.

7. Warranties. Vendor warrants the services will be performed in a professional and \
workmanlike manner. EXCEPT AS STATED, THE SERVICES ARE PROVIDED "AS IS".

8. Governing Law. This Agreement is governed by the laws of the State of Delaware.
"""


def _verdict_label(v: Verdict) -> str:
    return {Verdict.CONFIRMED: "confirmed", Verdict.PARTIAL: "partial", Verdict.UNSUPPORTED: "unsupported"}[v]


async def _main() -> None:
    keys = specialist_band_keys()
    if not keys:
        print(
            "Register specialist agents at app.band.ai and add "
            "BAND_SPECIALIST_<NAME>_KEY to .env (at least one), plus a BAND_REPORTER_KEY "
            "(or reuse BAND_MARKET_KEY) for the reporter. Exiting without spending."
        )
        return

    model = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")

    # Build the team: one CollaborationMember per specialty we hold a key for, each with
    # its OWN Band client (so it posts as itself) + a real SpecialistWorker brain.
    team: list[CollaborationMember] = []
    for name, key in keys.items():
        meta = _SPEC_META.get(name)
        if meta is None:
            continue  # an unknown specialty key — skip rather than guess a prompt
        area, prompt = meta
        team.append(
            CollaborationMember(
                specialty=name,
                area=area,
                band=make_http_band_client(key),
                auditor=SpecialistWorker(
                    name=name, area=area, system_prompt=prompt,
                    backend=make_backend("openai", model),
                ),
            )
        )

    # Optional cross-owner tax bot (a 2nd account) as an extra team member.
    owner2_key = (os.getenv("BAND_AGENT_OWNER2_KEY") or "").strip()
    if owner2_key and "tax" in _SPEC_META and not any(m.specialty == "tax" for m in team):
        area, prompt = _SPEC_META["tax"]
        team.append(
            CollaborationMember(
                specialty="tax",
                area=area,
                band=make_http_band_client(owner2_key),
                auditor=SpecialistWorker(
                    name="tax", area=area, system_prompt=prompt,
                    backend=make_backend("openai", model),
                ),
            )
        )

    if not team:
        print("No team could be built from the available keys. Exiting without spending.")
        return

    # The reporter: its own Band client (BAND_REPORTER_KEY, falling back to the market
    # key) + a real ReporterWorker brain.
    reporter_key = (
        os.getenv("BAND_REPORTER_KEY") or os.getenv("BAND_MARKET_KEY") or ""
    ).strip()
    if not reporter_key:
        print(
            "No reporter identity — set BAND_REPORTER_KEY (or BAND_MARKET_KEY) in .env "
            "so the reporter has a Band identity. Exiting without spending."
        )
        return
    reporter_band = make_http_band_client(reporter_key)
    try:
        reporter_me = await reporter_band.me()
    except httpx.HTTPStatusError as exc:
        print(f"Band /me failed for the reporter: {exc.response.status_code} — {exc.response.text}")
        return
    reporter_member = ReporterMember(
        band=reporter_band,
        reporter=ReporterWorker(make_backend("openai", model)),
        mention={
            "id": reporter_me.get("id"),
            "handle": reporter_me.get("handle") or "",
            "name": reporter_me.get("name") or "reporter",
        },
    )

    # The market creates the work room + adds every member (specialists + reporter).
    market_key = (os.getenv("BAND_MARKET_KEY") or next(iter(keys.values()))).strip()
    market = make_http_band_client(market_key)
    try:
        work_room_id = await market.create_room("Acme MSA — in-room team audit")
        for m in team:
            ident = await m.band.me()
            await market.add_participant(work_room_id, ident["id"])
        await market.add_participant(work_room_id, reporter_me["id"])
    except httpx.HTTPStatusError as exc:
        print(f"Band room setup failed: {exc.response.status_code} — {exc.response.text}")
        return

    verifier = Verifier(make_backend("openai", model))

    print(f"\nIn-room team audit — work room {work_room_id}")
    print(f"  team: {', '.join(m.specialty for m in team)}  |  reporter: {reporter_member.mention['name']}\n")

    try:
        result = await collaborate_in_room(
            work_room_id, SAMPLE_MSA, team, reporter_member, verifier
        )
    except httpx.HTTPStatusError as exc:
        req = exc.request
        print(f"\nBand API error during collaboration: {exc.response.status_code} on "
              f"{req.method} {req.url} — {exc.response.text}")
        return

    # 1. room transcript — who posted what -----------------------------------
    print("ROOM TRANSCRIPT:")
    try:
        transcript = await market.get_context(work_room_id)
    except httpx.HTTPStatusError:
        transcript = []
    if transcript:
        for msg in transcript:
            who = msg.get("sender_name") or msg.get("sender_id") or "?"
            content = (msg.get("content") or "").replace("\n", " ")
            if len(content) > 160:
                content = content[:157] + "..."
            print(f"  [{who}] {content}")
    else:
        print("  (context not visible to the market — see per-agent posts above)")

    # 2. verified specialist findings ----------------------------------------
    print(f"\nVERIFIED FINDINGS ({len(result.audited)}):")
    if result.audited:
        for af in result.audited:
            v = af.verdict
            ref = af.finding.clause_ref or "—"
            print(
                f"  • [{af.finding.worker:<12}] ({_verdict_label(v.verdict)}, "
                f"conf={v.confidence:.2f}, clause {ref}) {af.finding.claim}"
            )
    else:
        print("  (no findings posted)")

    # 3. reporter synthesis + its verdicts -----------------------------------
    print(f"\nREPORTER SYNTHESIS:\n  {result.report_summary}")
    print(f"\nVERIFIED REPORT CLAIMS ({len(result.report_audited)}):")
    if result.report_audited:
        for af in result.report_audited:
            v = af.verdict
            ref = af.finding.clause_ref or "—"
            print(
                f"  • ({_verdict_label(v.verdict)}, conf={v.confidence:.2f}, clause {ref}) "
                f"{af.finding.claim}"
            )
    else:
        print("  (no report claims)")

    # 4. headline ------------------------------------------------------------
    n_unsupported = sum(
        af.verdict.verdict is Verdict.UNSUPPORTED for af in result.all_audited
    )
    print(
        f"\nRESULT: {len(result.all_audited)} graded items "
        f"({len(result.audited)} findings + {len(result.report_audited)} report claims), "
        f"{n_unsupported} unsupported (caught + unpayable)."
    )


if __name__ == "__main__":
    asyncio.run(_main())
