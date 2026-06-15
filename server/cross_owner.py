"""Cross-owner recruit — the live-run beat where an agent the market DOESN'T OWN
joins the work room, gated by a REAL Band contact-consent handshake.

This is the hackathon's #1 hero moment: Band as the coordination layer ACROSS owners.
One specialist in the live roster is designated the cross-owner agent (its
``BAND_SPECIALIST_<NAME>_KEY`` is a SECOND Band account's key); before it is added to
the work room the market runs the inverse-auto-accept contact handshake with it, exactly
as ``market.marketplace.run_market_job`` / ``spikes/cross_owner_smoke.py`` do — then it
is recruited like any other specialist, but marked ``cross_owner=True`` so the UI shows
the cross-org marker + a recruit narration.

Configuration (all read from the env, lazily):
  * ``BAND_CROSS_OWNER_SPECIALTY`` — which specialty is the cross-owner one (default
    ``"tax"``). Unset/blank ⇒ NO cross-owner step (every specialist stays same-owner).
  * ``BAND_SPECIALIST_<SPECIALTY>_KEY`` — that specialty's Band key, set to the SECOND
    account's agent key. (Already read by ``specialist_band_keys()``; the cross-owner
    agent is therefore an ordinary roster member whose KEY happens to be a 2nd account.)
  * ``BAND_OWNER2_<SPECIALTY>_HANDLE`` — the cross-owner agent's Band handle (the
    market adds it by handle to close the handshake), e.g. ``BAND_OWNER2_TAX_HANDLE``.

Graceful-degradation contract (NEVER crash a live run):
  * No specialty configured, or its key/handle missing ⇒ no-op (same-owner everywhere).
  * Handshake/identity resolution failure ⇒ logged; the agent is treated as same-owner
    (still recruited via its key, just without the cross-owner marker/narration), so the
    rest of the team still runs end-to-end.

The owner label put on the cross-owner pool entry is derived from its handle's org
prefix (``other-org/tax-clause-bot`` ⇒ ``other-org``), falling back to ``"other"``.
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

#: Default cross-owner specialty when ``BAND_CROSS_OWNER_SPECIALTY`` is unset.
_DEFAULT_CROSS_OWNER_SPECIALTY = "tax"


def cross_owner_specialty() -> str:
    """The specialty designated cross-owner (``BAND_CROSS_OWNER_SPECIALTY``, default 'tax').

    A blank/unset value disables the cross-owner step entirely (returns "").
    """
    raw = os.environ.get("BAND_CROSS_OWNER_SPECIALTY")
    if raw is None:
        return _DEFAULT_CROSS_OWNER_SPECIALTY
    return raw.strip()


def cross_owner_handle(specialty: str) -> str:
    """The cross-owner agent's Band handle from ``BAND_OWNER2_<SPECIALTY>_HANDLE`` (or '')."""
    if not specialty:
        return ""
    return (os.environ.get(f"BAND_OWNER2_{specialty.upper()}_HANDLE") or "").strip()


def owner_label_for(handle: str) -> str:
    """Derive a human owner label from a handle's org prefix.

    ``"other-org/tax-clause-bot"`` ⇒ ``"other-org"``; ``"@acme/bot"`` ⇒ ``"acme"``;
    a handle with no ``/`` (or empty) ⇒ ``"other"``.
    """
    h = (handle or "").lstrip("@")
    if "/" in h:
        prefix = h.split("/", 1)[0].strip()
        if prefix:
            return prefix
    return "other"


async def establish_cross_owner_contact(market_band, cross_band, cross_handle: str) -> bool:
    """Run the inverse-auto-accept handshake market ⇄ cross-owner agent. True iff linked.

    The server owns BOTH Band clients (the market's and the cross-owner agent's, via its
    key), so it drives the full two-sided exchange like the offline spec / spike:

      1. the cross-owner agent expresses willingness toward the market (its half →
         pending), then
      2. the market adds the cross-owner agent by handle, which finds the pending inverse
         request and Band auto-approves — the contact is now established.

    This mirrors :func:`agent_exchange.band.consent.mutual_link` (side_a = market closes
    the loop). Returns True on an established/idempotent-already-contacts link, False on
    any failure (logged) so the caller can degrade to same-owner without crashing.
    """
    from agent_exchange.band.consent import mutual_link

    try:
        market_me = await market_band.me()
        market_handle = (market_me.get("handle") or "").strip()
        if not market_handle:
            logger.warning(
                "cross-owner handshake skipped: the market identity has no handle "
                "(cannot be added by the cross-owner agent)."
            )
            return False
        # side_a = market (closes the loop via its add), side_b = cross-owner agent.
        result = await mutual_link(market_band, market_handle, cross_band, cross_handle)
        status = (result or {}).get("status")
        if status not in ("approved", "pending"):
            logger.warning("cross-owner handshake returned status=%r (not linked)", status)
            return status == "approved"
        if status == "pending":
            # The market's closing add did not find the inverse request — not linked.
            logger.warning(
                "cross-owner handshake is still pending (the inverse add did not "
                "auto-approve); treating %s as same-owner.", cross_handle,
            )
            return False
        logger.info("cross-owner contact established with %s → approved", cross_handle)
        return True
    except Exception as exc:  # noqa: BLE001 — a handshake failure must never crash the run.
        logger.warning("cross-owner handshake with %s failed: %s", cross_handle, exc)
        return False
