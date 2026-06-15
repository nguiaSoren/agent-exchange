"""The bidding orchestrator — the market-side fan-out that turns a posted `Job`
into a set of `Bid`s.

This is the "auction" stage. Given a `Job` and a roster of candidate
`BiddingAgent`s (one per clause-audit specialty), the market:

  1. opens a Band room for the job,
  2. @mentions every candidate with the job posting,
  3. lets each candidate run a CHEAP relevance probe (one small model call on a
     contract *preview*, NOT the full audit) and decide whether to bid + at what
     price, then post its bid back into the room,
  4. collects the bids deterministically for the next box (hiring) to consume.

The expensive work (the full clause audit) happens later, only for the agent that
wins. The probe here is deliberately cheap so a six-way fan-out costs ~six small
calls, not six full audits.

Design / discipline notes:
  - **Fail-safe probe.** `relevance_probe` NEVER raises: any parse or shape error
    collapses to "don't bid" (`{"bid": False, "relevance": 0.0, "price_cents": 0}`),
    so a flaky model removes a bidder rather than crashing the round.
  - **L5 — bounded fan-out, no swallowed failures.** `run_bidding` caps concurrency
    with an `asyncio.Semaphore` and wraps each agent in a per-agent guard: a raising
    agent is caught, logged at WARNING, and treated as "no bid" — it never takes the
    round down, and the failure is on the record (logged), not silently dropped.
  - **Money is atomic ints.** The probe quotes whole US cents; the bid carries USDC
    atomic units (1 USDC = 10**6 atomic, so 1 cent = 10**4 atomic). No floats past
    this boundary.
  - **Determinism.** Collected bids are sorted by `.worker` so the same roster always
    yields the same ordering regardless of which probe returned first.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from ..band.client import BandClient
from ..core.backend import ModelBackend
from ..core.types import Message
from .schema import Bid, Job, ReputationStore

logger = logging.getLogger(__name__)

# 1 USDC = 10**6 atomic units (USDC has 6 decimals). $0.01 (one cent) = 10**4 atomic.
_ATOMIC_PER_CENT = 10**4

# The fail-safe verdict every error path returns: a clean "decline to bid".
_DECLINE: dict[str, Any] = {"bid": False, "relevance": 0.0, "price_cents": 0}

def probe_system(document: str = "contract") -> str:
    """Build the relevance-probe system prompt for a given document type.

    The document word is parameterized so the same cheap "should I bid?" probe
    works for any document type (a contract, an NDA, ...). The default
    ``"contract"`` reproduces the original prompt verbatim.

    Args:
        document: The document-type word (lowercase), e.g. ``"contract"`` or
            ``"nda"``.

    Returns:
        The full probe system prompt string.
    """
    doc = document
    return (
        f"You are a clause-audit specialist deciding whether to bid on a {doc}-audit "
        f"job. Be cheap and decisive. Given your clause area and a short PREVIEW of the "
        f"{doc}, judge whether the {doc} plausibly contains clauses in YOUR area "
        f"that are worth auditing, and — if so — what you would charge to audit the full "
        f"{doc} for that area.\n"
        'Reply with ONE JSON object and nothing else: '
        '{"bid": true|false, "relevance": <0..1>, "price_cents": <integer cents>}.\n'
        "- bid: true only if your area is plausibly present and worth auditing.\n"
        "- relevance: your confidence (0..1) that your area is materially present.\n"
        "- price_cents: your asking price in whole US cents (integer); 0 if not bidding.\n"
        "Output ONLY the JSON object — no prose, no markdown fences."
    )


# Module-level default (document="contract") so existing importers keep working.
_PROBE_SYSTEM = probe_system()


def _extract_json_object(text: str) -> dict:
    """Pull the first JSON object out of a model completion, robustly.

    Strips Markdown code fences, then scans for the first balanced ``{...}`` block
    and ``json.loads`` it. Raises on anything that isn't a well-formed JSON object —
    callers translate that into the fail-safe decline.

    Args:
        text: Raw model completion text.

    Returns:
        The parsed JSON object as a ``dict``.

    Raises:
        ValueError: If no balanced object is found.
        json.JSONDecodeError: If the located span isn't valid JSON.
        TypeError: If the parsed value isn't a JSON object (dict).
    """
    cleaned = text.strip()
    if cleaned.startswith("```"):
        # Drop the opening fence line (``` or ```json) and a trailing fence if present.
        cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else ""
        if cleaned.rstrip().endswith("```"):
            cleaned = cleaned.rstrip()[: -3]
    cleaned = cleaned.strip()

    start = cleaned.find("{")
    if start == -1:
        raise ValueError("no JSON object in completion")
    depth = 0
    for i in range(start, len(cleaned)):
        ch = cleaned[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                obj = json.loads(cleaned[start : i + 1])
                if not isinstance(obj, dict):
                    raise TypeError("parsed JSON is not an object")
                return obj
    raise ValueError("unbalanced JSON object in completion")


async def relevance_probe(
    area: str,
    contract_preview: str,
    backend: ModelBackend,
    *,
    document_label: str = "contract",
) -> dict:
    """Cheap "should I bid, and for how much?" probe for one clause area.

    Runs a single small model call: given the clause `area` and a contract
    `contract_preview`, the model returns a JSON verdict
    ``{"bid", "relevance", "price_cents"}``. Parsing is hardened and fully
    fail-safe — ANY error (network, malformed JSON, wrong shape, bad types)
    collapses to a clean decline so the bidder simply drops out of the round.

    Args:
        area: The specialist's clause area (human-readable), e.g.
            ``"liability caps, limitations, and disclaimers of damages"``.
        contract_preview: A short slice of the document (from ``Job.preview()``);
            kept small so the probe is cheap.
        backend: The (cheap) model backend to run the probe on.
        document_label: The document-type word for the probe prompt (default
            ``"contract"``).

    Returns:
        A normalised dict ``{"bid": bool, "relevance": float in [0,1],
        "price_cents": int >= 0}``. On any failure: ``{"bid": False,
        "relevance": 0.0, "price_cents": 0}``.
    """
    messages = [
        Message.system(probe_system(document_label)),
        Message.user(
            f"YOUR CLAUSE AREA: {area}\n\n"
            f"{document_label.upper()} PREVIEW (first part only):\n{contract_preview}\n\n"
            "Return your JSON verdict now."
        ),
    ]
    try:
        result = await backend.complete(messages, temperature=0.0, max_tokens=120)
        raw = _extract_json_object(result.text)
        bid = bool(raw["bid"])
        relevance = float(raw["relevance"])
        price_cents = int(raw["price_cents"])
    except Exception as exc:  # noqa: BLE001 — fail-safe: any probe error ⇒ decline.
        logger.warning("relevance_probe failed for area=%r: %s", area, exc)
        return dict(_DECLINE)

    # Clamp to the valid ranges regardless of what the model said.
    relevance = min(1.0, max(0.0, relevance))
    price_cents = max(0, price_cents)
    return {"bid": bid, "relevance": relevance, "price_cents": price_cents}


class BiddingAgent:
    """One specialist's bidding participant in the market.

    Wraps a specialty (the stable worker id stamped on bids + reputation), the
    clause `area` (fed to the probe), the agent's OWN `BandClient` (so it can read
    the job posting and post its bid as itself), a cheap `probe_backend`, and the
    shared `ReputationStore`.

    A `BiddingAgent` decides — per job — whether to bid via the cheap probe, and if
    so posts a `Bid` back into the room and returns it. It does NO auditing here.
    """

    def __init__(
        self,
        specialty: str,
        area: str,
        band: BandClient,
        probe_backend: ModelBackend,
        reputation: ReputationStore,
        *,
        document_label: str = "contract",
    ) -> None:
        """Construct a bidding participant.

        Args:
            specialty: Stable worker id (e.g. ``"liability"``) — stamped on the `Bid`
                and used to look up reputation. Must match the specialist's name.
            area: Human-readable clause area passed to the relevance probe.
            band: This agent's own Band client (used to read the job message and post
                its bid as itself).
            probe_backend: Cheap model backend for the relevance probe.
            reputation: Shared reputation store; a snapshot is attached to each bid.
            document_label: The document-type word threaded into the relevance probe
                (default ``"contract"``).
        """
        self.specialty = specialty
        self.area = area
        self.band = band
        self.probe_backend = probe_backend
        self.reputation = reputation
        self.document_label = document_label

    async def consider_and_bid(
        self, job: Job, room_id: str, market_mention: dict
    ) -> Bid | None:
        """Probe the job and, if relevant, post + return a `Bid`; else decline.

        Reads the (job) message addressed to this agent, runs the cheap relevance
        probe on the job preview, and either declines (marks the message processed,
        returns ``None``) or builds a `Bid`, posts a one-line human summary plus a
        fenced JSON bid into the room @mentioning the market, marks the message
        processed, and returns the bid.

        Args:
            job: The job under consideration (authoritative; used even if the inbox
                message is missing).
            room_id: The Band room hosting this job.
            market_mention: The market's mention dict ``{id, handle, name}`` to
                @mention on the posted bid.

        Returns:
            The posted `Bid`, or ``None`` if the agent declined to bid.
        """
        msg = await self.band.get_next_message(room_id)

        r = await relevance_probe(
            self.area,
            job.preview(),
            self.probe_backend,
            document_label=self.document_label,
        )

        if not r["bid"] or r["relevance"] <= 0:
            if msg:
                await self.band.mark_processed(room_id, msg["id"])
            return None

        price_atomic = int(r["price_cents"]) * _ATOMIC_PER_CENT
        rep = self.reputation.get(self.specialty)
        bid = Bid(
            worker=self.specialty,
            job_id=job.job_id,
            price_atomic=price_atomic,
            relevance_confidence=float(r["relevance"]),
            reputation=rep,
        )

        price_usdc = price_atomic / 10**6
        summary = (
            f"@market {self.specialty} bids on '{job.title}': "
            f"${price_usdc:,.2f} USDC (relevance {bid.relevance_confidence:.2f})."
        )
        payload = json.dumps(
            {
                "worker": bid.worker,
                "price_atomic": bid.price_atomic,
                "relevance": bid.relevance_confidence,
            }
        )
        content = f"{summary}\n```json\n{payload}\n```"
        await self.band.post_message(room_id, content, mentions=[market_mention])

        if msg:
            await self.band.mark_processed(room_id, msg["id"])
        return bid


async def run_bidding(
    job: Job,
    market_band: BandClient,
    agents: list[BiddingAgent],
    *,
    invite: list[dict] | None = None,
    max_concurrency: int = 6,
) -> tuple[str, list[Bid]]:
    """Run one bidding round for `job` over a roster of `agents`.

    Orchestrates the full market-side flow: open a room, add every candidate, post a
    single job message @mentioning ALL candidates, then fan out the candidates'
    relevance-probe-and-bid concurrently under a `Semaphore`. Per-agent failures are
    caught and logged (L5) — a raising agent counts as "no bid" and never crashes the
    round. Collected bids are returned sorted by ``.worker`` for deterministic output.

    Who gets **added + @mentioned** is controlled by `invite`:
      - When `invite` is provided (a list of ``{id, handle, name}`` mention dicts,
        e.g. from discovery), those identities are added to the room and @mentioned.
      - When `invite is None` (default), the identities are derived from `agents` by
        calling each agent's ``band.me()`` — the original behavior.
    Either way, every agent in `agents` is fanned out to bid via `consider_and_bid`;
    `invite` only changes WHO is added + @mentioned, not who bids.

    Args:
        job: The job to auction.
        market_band: The market's OWN Band client (creates the room + posts the job).
        agents: Candidate bidding agents (each with its own Band client) — all fan out
            to bid.
        invite: Optional explicit ``{id, handle, name}`` mention dicts to add +
            @mention. If ``None``, derived from `agents`.
        max_concurrency: Cap on concurrent probe/bid calls (L5 semaphore bound).

    Returns:
        ``(room_id, bids)`` — the room hosting the auction and the bids placed,
        sorted by worker id. ``bids`` may be empty (no one bid).
    """
    room_id = await market_band.create_room(job.title)

    market = await market_band.me()
    market_mention = {
        "id": market["id"],
        "handle": market.get("handle", ""),
        "name": market.get("name", "market"),
    }

    # Determine the identities to add + @mention. When `invite` is given, use those
    # discovered identities directly; otherwise derive them from the agents (original
    # behavior) by asking each agent's own Band client who it is.
    if invite is not None:
        agent_mentions: list[dict] = [
            {
                "id": m["id"],
                "handle": m.get("handle", ""),
                "name": m.get("name", m["id"]),
            }
            for m in invite
        ]
    else:
        agent_mentions = []
        for agent in agents:
            aid = await agent.band.me()
            agent_mentions.append(
                {
                    "id": aid["id"],
                    "handle": aid.get("handle", ""),
                    "name": aid.get("name", agent.specialty),
                }
            )

    # Add every invited/derived identity to the room so the job posting can @mention
    # the whole roster in a single message.
    for mention in agent_mentions:
        await market_band.add_participant(room_id, mention["id"])

    budget_usdc = job.budget_atomic / 10**6
    job_content = (
        f"JOB: {job.title}\n"
        f"Budget: up to ${budget_usdc:,.2f} USDC.\n"
        "Bid if your clause-audit specialty is relevant to this contract."
    )
    await market_band.post_message(room_id, job_content, mentions=agent_mentions)

    # L5 — bounded fan-out. Each agent runs under the semaphore; a raising agent is
    # caught + logged and treated as no bid, never taking the round down.
    sem = asyncio.Semaphore(max_concurrency)

    async def _guarded(agent: BiddingAgent) -> Bid | None:
        async with sem:
            try:
                return await agent.consider_and_bid(job, room_id, market_mention)
            except Exception as exc:  # noqa: BLE001 — isolate one agent's failure.
                logger.warning(
                    "bidding agent %r raised; treating as no bid: %s",
                    agent.specialty,
                    exc,
                )
                return None

    results = await asyncio.gather(*(_guarded(a) for a in agents))
    bids = [b for b in results if b is not None]
    bids.sort(key=lambda b: b.worker)
    return room_id, bids


def build_bidding_agents(
    specialists: Any,
    key_map: dict[str, str],
    *,
    probe_backend: ModelBackend,
    reputation: ReputationStore,
    band_factory: Any,
    document_label: str = "contract",
) -> list[BiddingAgent]:
    """Build one `BiddingAgent` per specialist that has a Band key.

    Agent-count-agnostic: a specialist with no entry in `key_map` is simply skipped
    (it won't participate this round). Handles both the `SPECIALISTS` tuple shape
    (``(name, area, system_prompt)``) and objects exposing ``.name`` + ``.area``.

    Args:
        specialists: Iterable of specialists — each a ``(name, area, ...)`` tuple OR
            an object with ``.name`` and ``.area`` attributes.
        key_map: ``name → Band API key``. Only specialists present here get an agent.
        probe_backend: Cheap model backend shared by every agent's probe.
        reputation: Shared reputation store passed to every agent.
        band_factory: ``key -> BandClient`` factory; called with the specialist's key
            to construct that agent's own Band client.
        document_label: The document-type word threaded into every agent (default
            ``"contract"``).

    Returns:
        A `BiddingAgent` per keyed specialist, in input order.
    """
    agents: list[BiddingAgent] = []
    for spec in specialists:
        if isinstance(spec, tuple):
            name, area = spec[0], spec[1]
        else:
            name, area = spec.name, spec.area
        key = key_map.get(name)
        if key is None:
            continue
        band = band_factory(key)
        agents.append(
            BiddingAgent(
                specialty=name,
                area=area,
                band=band,
                probe_backend=probe_backend,
                reputation=reputation,
                document_label=document_label,
            )
        )
    return agents
