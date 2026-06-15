"""Shared types for the discovery → recruiting marketplace wiring (the locked contract).

The same-owner flow this box adds: the market **discovers** its account's agent pool
via Band contacts/peers (`AgentIdentity`s), runs bidding among them, hires a team, then
**recruits** only the hired into a dedicated WORK room (`RecruitedTeam`). `MarketResult`
is the full lifecycle of one job. These frozen types are the seam every piece codes
against, so the Band layer, discovery, recruiting, and tests can be built in parallel.
"""

from __future__ import annotations

from dataclasses import dataclass

from .hiring_types import HiringDecision
from .schema import Bid


@dataclass(frozen=True, slots=True)
class AgentIdentity:
    """A discoverable agent in the market's same-owner pool (from Band contacts/peers)."""

    id: str
    handle: str
    name: str

    def mention(self) -> dict:
        """The @mention payload Band routing expects (`{id, handle, name}`)."""
        return {"id": self.id, "handle": self.handle, "name": self.name}


@dataclass(frozen=True, slots=True)
class RecruitedTeam:
    """Outcome of recruiting the hired team into a dedicated work room."""

    work_room_id: str
    recruited: tuple[str, ...]      # worker names added to the work room as participants
    skipped: tuple[str, ...]        # hired workers with no known identity (could not add)

    @property
    def n_recruited(self) -> int:
        return len(self.recruited)


@dataclass(frozen=True, slots=True)
class MarketResult:
    """The full lifecycle of one market job: discover → bid → hire → recruit."""

    pool: tuple[AgentIdentity, ...]     # the discovered same-owner pool
    bidding_room_id: str
    bids: tuple[Bid, ...]
    decision: HiringDecision
    team: RecruitedTeam
