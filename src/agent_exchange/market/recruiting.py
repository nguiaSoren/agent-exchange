"""Team **recruiting** — the second room in the two-room market model.

All candidates bid in a single shared BIDDING room. Once a `HiringDecision`
names the team, recruiting opens a *fresh, dedicated* WORK room and pulls in
ONLY the hired workers: declined candidates are never added (that separation is
the entire point of the two-room model — the work room's signal stays clean of
losing bidders). A single kickoff message @mentions the recruited team so they
know the audit has begun.

Design / discipline notes:
  - **Best-effort Band I/O.** Each Band call (add-participant, kickoff post) is
    wrapped so one failure is logged and swallowed — a single bad add must not
    abort recruiting the rest of the team.
  - **Hired-but-unknown ⇒ skipped.** A hired worker with no entry in
    `mention_for` cannot be routed to, so it is recorded in `skipped` (never
    silently dropped) and simply not added.
"""

from __future__ import annotations

import logging

from ..band.client import BandClient
from .hiring_types import HiringDecision
from .marketplace_types import RecruitedTeam

logger = logging.getLogger(__name__)


async def recruit_team(
    decision: HiringDecision,
    market_band: BandClient,
    *,
    mention_for: dict[str, dict],
    work_room_title: str = "Audit — work room",
) -> RecruitedTeam:
    """Recruit the hired team into a fresh, dedicated WORK room.

    Opens a new work room, adds each hired worker that has a known identity, and
    posts ONE kickoff message @mentioning the whole recruited team. Declined
    workers are never added. Hired workers missing from ``mention_for`` are
    recorded in ``skipped``. Every Band call is best-effort: a failure is logged
    and swallowed so one bad call can't abort the rest.

    Args:
        decision: The hiring outcome naming who was hired (`decision.hired`).
        market_band: The market's OWN Band client (creates the work room + posts).
        mention_for: ``worker -> {"id", "handle", "name"}`` mention payloads. The
            hired ``Hire.worker`` is the lookup key.
        work_room_title: Title for the fresh work room.

    Returns:
        A :class:`RecruitedTeam` with the new ``work_room_id`` and the ``recruited``
        / ``skipped`` worker-name tuples.
    """
    work_room = await market_band.create_room(work_room_title)

    recruited: list[str] = []
    skipped: list[str] = []
    recruited_mentions: list[dict] = []

    for hire in decision.hired:
        mention = mention_for.get(hire.worker)
        if mention is None:
            skipped.append(hire.worker)
            continue
        try:
            await market_band.add_participant(work_room, mention["id"])
        except Exception:
            logger.exception(
                "Band add_participant failed for hire %s in work room %s",
                hire.worker,
                work_room,
            )
            skipped.append(hire.worker)
            continue
        recruited.append(hire.worker)
        recruited_mentions.append(mention)

    if recruited_mentions:
        handles = " ".join(f"@{m['name']}" for m in recruited_mentions)
        content = (
            f"{handles} You're hired — this is the work room for "
            f"'{work_room_title}'. Begin the audit."
        )
        try:
            await market_band.post_message(
                work_room, content, mentions=recruited_mentions
            )
        except Exception:
            logger.exception(
                "Band kickoff post failed in work room %s", work_room
            )

    return RecruitedTeam(
        work_room_id=work_room,
        recruited=tuple(recruited),
        skipped=tuple(skipped),
    )
