"""End-to-end market compose — one job through the full lifecycle.

`run_market_job` chains the four market stages into a single `MarketResult`:

  1. **discover** — find the account's same-owner agent pool via Band
     (`discover_pool`), so the roster isn't hardcoded.
  2. **bid** — open a BIDDING room and run the auction over the running agents
     (`run_bidding`); every candidate probes the job and posts a bid.
  3. **hire** — score the bids and select a team under budget (`policy.select`).
  4. **recruit** — open a fresh, dedicated WORK room and pull ONLY the hired team
     into it (`recruit_team`) — the two-room model.

The discovered `pool` drives the bidding invite (who is added to the room and
@mentioned with the job); it also rides on the result for observability. Each
running agent's live identity is harvested (`specialty -> me()`) into the `mention_for`
map so the hired workers — keyed by their specialty, which equals
`Hire.worker` — can be @mentioned into the work room.
"""

from __future__ import annotations

from ..band.client import BandClient
from ..band.consent import establish_contact
from .bidding import BiddingAgent, run_bidding
from .discovery import discover_pool
from .hiring import HiringPolicy, budget_guard_for_job
from .marketplace_types import MarketResult, RecruitedTeam
from .recruiting import recruit_team
from .schema import Job

# Default model IDs — match the live server (server/app.py) so callers that omit
# these parameters get the same cost estimate as a real run.
_DEFAULT_WORKER_MODEL = "gpt-4.1-mini"
_DEFAULT_VERIFIER_MODEL = "gpt-4.1"


async def run_market_job(
    job: Job,
    market_band: BandClient,
    agents: list[BiddingAgent],
    policy: HiringPolicy,
    *,
    work_room_title: str | None = None,
    cross_owner_handles: list[str] | None = None,
    worker_model: str = _DEFAULT_WORKER_MODEL,
    verifier_model: str = _DEFAULT_VERIFIER_MODEL,
) -> MarketResult:
    """Run one job through discover → bid → hire → recruit, returning the full result.

    Args:
        job: The job to auction and staff.
        market_band: The market's OWN Band client (discovers the pool, opens rooms,
            posts the job and the kickoff).
        agents: The running bidding agents (each with its own Band client + specialty).
        policy: The hiring policy that turns scored bids into a team.
        work_room_title: Optional explicit title for the WORK room; defaults to
            ``"{job.title} — work room"``.
        cross_owner_handles: Optional handles of agents owned by someone ELSE that the
            market wants in this job. Before discovery, the market expresses willingness
            to contact each (its half of the inverse handshake); each cross-owner bot is
            expected to have already added the market, so the market's add triggers
            inverse auto-accept and the contact is established. Once a contact, the agent
            is picked up by `discover_pool` (peers ∪ contacts) and invited to bid like
            any other. ``None`` (the default) is a no-op — fully backward-compatible.
        worker_model: Model ID used by each worker agent (for budget-guard cost
            projection). Defaults to ``"gpt-4.1-mini"``. Set to the same value
            the live server uses so cost estimates are accurate.
        verifier_model: Model ID used by the verifier agent (for budget-guard cost
            projection). Defaults to ``"gpt-4.1"``.

    Returns:
        A :class:`MarketResult` capturing the discovered pool, the bidding room and
        bids, the hiring decision, and the recruited team.
    """
    # a0. Consent handshake (market's half): express willingness to contact each
    #     cross-owner agent. With the counterpart having already added the market,
    #     this triggers inverse auto-accept so the agent becomes an established
    #     contact and is discovered below. A no-op when no handles are given.
    if cross_owner_handles:
        for handle in cross_owner_handles:
            await establish_contact(market_band, handle)

    # a. Discover the agent pool: same-owner peers ∪ established contacts (fail-safe:
    #    empty on any Band error).
    pool = await discover_pool(market_band)

    # Harvest each running agent's TRUE identity once (one me() per agent). A
    # cross-owner agent surfaces in discovery via a Band /contacts record whose `id`
    # is a contact-record id, NOT the agent id that `add_participant` needs — but the
    # agent is running here, so its me() carries the real id. Index it by handle (to
    # correct the bidding invite) and by specialty (== Hire.worker, for the work-room
    # @mentions). Same-owner peers already carry the real id, so this is a no-op there.
    real_id_by_handle: dict[str, str] = {}
    mention_for: dict[str, dict] = {}
    for agent in agents:
        me = await agent.band.me()
        ident = {"id": me["id"], "handle": me.get("handle", ""), "name": me.get("name", agent.specialty)}
        mention_for[agent.specialty] = ident
        if ident["handle"]:
            real_id_by_handle[ident["handle"]] = me["id"]

    # b. Run the auction. Discovery DRIVES who is invited (Band requires participation
    #    to receive @mentions); each discovered member is resolved to its TRUE agent id
    #    via the running agent's me() (correcting the cross-owner contact-record id).
    #    Empty pool → invite=None → run_bidding falls back to the configured agents.
    #    Dedup by the resolved id: an agent that surfaces in BOTH /peers and /contacts
    #    (peer-id vs contact-record-id) collapses to one real id by handle, so without
    #    this it would be @mentioned twice (Band rejects duplicate mentions).
    invite_by_id: dict[str, dict] = {}
    for p in pool:
        rid = real_id_by_handle.get(p.handle, p.id)
        invite_by_id.setdefault(rid, {"id": rid, "handle": p.handle, "name": p.name})
    invite = list(invite_by_id.values()) or None
    bidding_room, bids = await run_bidding(job, market_band, agents, invite=invite)

    # c. Score the bids and select a team under budget (pure, no I/O).
    #    The budget guard projects the real token cost before committing any hire:
    #    n_workers · estimate_cost(worker_model) + estimate_cost(verifier_model).
    #    A BLOCKED decision (over_budget=True, budget_block_reason set) skips recruiting.
    guard = budget_guard_for_job(
        job,
        worker_model=worker_model,
        verifier_model=verifier_model,
        n_workers=len(agents),
    )
    decision = policy.select(job, bids, budget_guard=guard)

    # d. If the budget guard blocked the job, surface the decline without recruiting.
    if decision.over_budget and decision.budget_block_reason is not None:
        return MarketResult(
            pool=tuple(pool),
            bidding_room_id=bidding_room,
            bids=tuple(bids),
            decision=decision,
            team=RecruitedTeam(
                work_room_id="",
                recruited=(),
                skipped=(),
            ),
        )

    # e. Recruit ONLY the hired into a fresh, dedicated work room (two-room model).
    team = await recruit_team(
        decision,
        market_band,
        mention_for=mention_for,
        work_room_title=work_room_title or f"{job.title} — work room",
    )

    # f. Package the full lifecycle.
    return MarketResult(
        pool=tuple(pool),
        bidding_room_id=bidding_room,
        bids=tuple(bids),
        decision=decision,
        team=team,
    )
