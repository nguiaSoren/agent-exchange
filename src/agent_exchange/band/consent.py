"""Consent handshake — the mutual-contact step that gates cross-owner hiring.

Band auto-visibility only covers *same-owner* siblings (peers). To bring an agent
owned by someone ELSE into a room, the two sides must first become established
CONTACTS. This module is the market's side of that handshake plus two helpers that
drive the full two-sided exchange in tests/spikes.

The model is **inverse auto-accept**: a contact link is established the moment BOTH
parties have expressed willingness by calling `add_contact` on each other (in either
order). There is no human approve step on the happy path — when side B has already
added side A, side A's `add_contact(B)` finds B's pending request and Band
auto-approves the pair, returning ``{"status": "approved"}``. If the other side
hasn't added yet, the request sits ``{"status": "pending"}`` until they do.

Once a pair is contacts, the cross-owner agent appears in `discover_pool`
(peers ∪ contacts) and is invited to bid like any other agent.

`auto_approve_requests` is the EXPLICIT-approve variant — kept available for flows
that prefer to gate inbound requests by hand rather than rely on inverse-accept. The
default marketplace path does not need it.
"""

from __future__ import annotations

import logging

from .client import BandClient

logger = logging.getLogger(__name__)


async def establish_contact(requester_band: BandClient, target_handle: str) -> dict:
    """Express this side's willingness to contact ``target_handle`` (market's half).

    Calls ``add_contact(target_handle)`` on the requester's Band client and returns
    its result verbatim. Under inverse auto-accept this returns ``{"status":
    "approved"}`` if the target had already added the requester (the link is now
    established), otherwise ``{"status": "pending"}`` until the target reciprocates.

    Args:
        requester_band: The Band client expressing willingness (e.g. the market's).
        target_handle: The handle of the cross-owner agent to contact.

    Returns:
        The ``add_contact`` result dict, e.g. ``{"status": "approved"|"pending"}``.
    """
    result = await requester_band.add_contact(target_handle)
    logger.info("contact with %s → %s", target_handle, result.get("status"))
    return result


async def auto_approve_requests(responder_band: BandClient) -> list[str]:
    """Approve every incoming pending contact request (explicit-approve variant).

    Polls ``list_contact_requests()`` and approves each via
    ``respond_to_contact_request(from_handle, "approve")``. This is the manual gate
    kept available for flows that don't rely on inverse auto-accept; the default
    marketplace path doesn't use it.

    Best-effort: each request is approved under its own try/except so one bad request
    (already gone, transient error) never blocks the rest — failures are logged and
    skipped.

    Args:
        responder_band: The Band client whose inbound requests are being approved.

    Returns:
        The ``from_handle``s that were successfully approved, in request order.
    """
    approved: list[str] = []
    requests = await responder_band.list_contact_requests()
    for req in requests:
        from_handle = req.get("from_handle")
        if not from_handle:
            continue
        try:
            await responder_band.respond_to_contact_request(from_handle, "approve")
            approved.append(from_handle)
            logger.info("approved contact request from %s", from_handle)
        except Exception as exc:  # noqa: BLE001 — best-effort: one bad request can't block the rest.
            logger.warning("failed to approve contact request from %s: %s", from_handle, exc)
    return approved


async def mutual_link(
    side_a: BandClient, a_handle: str, side_b: BandClient, b_handle: str
) -> dict:
    """Drive the full two-sided inverse handshake, returning the final status.

    Runs both halves of the inverse-accept exchange:
      1. ``side_b.add_contact(a_handle)`` — B expresses willingness (records B's
         pending request toward A).
      2. ``side_a.add_contact(b_handle)`` — A's add finds B's pending request and
         triggers inverse auto-accept, establishing the link.

    Useful for tests/spikes that own both Band clients and want a contact established
    in one call. Production callers typically drive only ONE side (their own) via
    `establish_contact`, relying on the counterpart to have added them already.

    Args:
        side_a: One side's Band client (the one whose add closes the loop).
        a_handle: ``side_a``'s handle (the one ``side_b`` adds).
        side_b: The other side's Band client (expresses willingness first).
        b_handle: ``side_b``'s handle (the one ``side_a`` adds to trigger accept).

    Returns:
        The final ``add_contact`` result from ``side_a``, e.g.
        ``{"status": "approved"}`` once the pair is linked.
    """
    await side_b.add_contact(a_handle)
    result = await side_a.add_contact(b_handle)
    logger.info("mutual link %s ⇄ %s → %s", a_handle, b_handle, result.get("status"))
    return result
