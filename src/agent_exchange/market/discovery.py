"""Agent **discovery** — the market finds its available agent pool via Band
instead of a hardcoded roster.

The pool is the UNION of two Band sources:
  - `list_peers()`   — same-owner siblings (Band `GET /peers`, auto-visible).
  - `list_contacts()` — ESTABLISHED cross-owner contacts (Band `GET /contacts`),
    i.e. agents from a different owner that completed the consent handshake.

Each `{id, handle, name}` becomes an `AgentIdentity`; the market's own id (and any
explicitly excluded id) is dropped, and duplicates (an agent that is both a peer and
a contact) collapse by id. The resulting pool feeds bidding/recruiting — so a
cross-owner agent automatically becomes biddable the moment it becomes a contact.

Design / discipline notes:
  - **Fail-safe per source.** Discovery must NEVER crash the market. If either
    `list_peers()` or `list_contacts()` raises (network blip, auth, shape error),
    that source contributes an empty list (logged at WARNING); the other still
    counts. The caller can always fall back to its configured agents.
  - **Deterministic order.** The returned pool is sorted by `id`.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

from ..band.client import BandClient
from .marketplace_types import AgentIdentity

logger = logging.getLogger(__name__)


async def _safe(source: Callable[[], Awaitable[list[dict]]], label: str) -> list[dict]:
    """Call a discovery source, returning ``[]`` (logged) on any failure."""
    try:
        return await source()
    except Exception as exc:  # noqa: BLE001 — fail-safe: discovery never crashes the market.
        logger.warning("discover_pool: %s() failed; that source contributes nothing: %s", label, exc)
        return []


async def discover_pool(
    market_band: BandClient, *, exclude: set[str] | None = None
) -> list[AgentIdentity]:
    """Discover the market's agent pool: same-owner peers ∪ established contacts.

    Args:
        market_band: The market's OWN Band client.
        exclude: Optional agent ids to omit (in addition to the market's own id).

    Returns:
        The discovered pool as `AgentIdentity`s, deduped by id and sorted by id.
        Either Band source failing degrades to empty for that source, never raises.
    """
    excluded: set[str] = set(exclude) if exclude else set()
    me = await market_band.me()
    excluded.add(me["id"])

    peers = await _safe(market_band.list_peers, "list_peers")
    contacts = await _safe(market_band.list_contacts, "list_contacts")

    seen: dict[str, AgentIdentity] = {}
    seen_handles: set[str] = set()
    for entry in (*peers, *contacts):
        aid = entry["id"]
        handle = entry.get("handle", "")
        # Dedup by id AND by handle: the same agent can surface in both /peers and
        # /contacts (or via multiple contact records) under one handle with different
        # ids — collapse to a single pool entry. Band handles are unique per agent.
        if aid in excluded or aid in seen or (handle and handle in seen_handles):
            continue
        seen[aid] = AgentIdentity(id=aid, handle=handle, name=entry.get("name", aid))
        if handle:
            seen_handles.add(handle)

    return [seen[aid] for aid in sorted(seen)]
