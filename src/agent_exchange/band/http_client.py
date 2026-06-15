"""Real HTTP implementation of `BandClient` against the live Band Agent API.

`HttpBandClient` is the production counterpart to `FakeBandClient` (in
`band/client.py`): same locked `BandClient` surface, but every call hits the real
Band Agent API over async `httpx`. The endpoint shapes, body wrappers, and gotchas
are ported VERBATIM from the proven live spike `spikes/band_room.py`
(read the canonical source, never default request shapes from memory):

  base    https://app.band.ai/api/v1/agent      auth header  X-API-Key: <agent_key>
  GET   /me                                     → {data:{id,handle,name,...}}
  GET   /peers                                  → {data:[{id,handle,name,...}]}  (same-owner pool)
  GET   /contacts                               → {data:[{id,handle,name,...}]}  (established cross-owner links)
  POST  /contacts/add        {handle}           → {data:{id,status}}     status pending|approved
  GET   /contacts/requests                      → {data:{received:[{from_handle,from_name,id,...}],sent:[...]}}
  POST  /contacts/requests/respond  {handle,action}  → {data:{id,status}}  action approve|reject(|cancel)
  POST  /chats                {chat:{title}}    → {data:{id,...}}        (creator = owner)
  POST  /chats/{id}/participants  {participant:{participant_id}}
  POST  /chats/{id}/messages  {message:{content,mentions}}  → {data:{...}}
  GET   /chats/{id}/messages/next               → {data: <msg>|null}
  GET   /chats/{id}/context                     → {data: [<msg>, ...]}
  POST  /chats/{id}/messages/{id}/processed     → advance the queue (best-effort)

Load-bearing gotchas encoded here (each cost a live debugging cycle in the spike):
  - `create_room` REQUIRES the `{"chat": {...}}` wrapper. The docs show body `{}`,
    which 422s — the real API wraps like message/participant do.
  - `get_next_message` returns `{"data": null}` (not 404) when the queue is empty;
    that maps to `None`, not an error.
  - `mark_processed` 422s on a truly empty body, so we send a minimal `{}`; and
    because it is pure queue hygiene, ANY 4xx on THIS call is logged + swallowed
    (best-effort, never raises) so a hygiene blip can't abort the bidding loop.

Transient-failure handling: a single retry predicate enumerates
every transient class — `httpx` TimeoutException / ConnectError / ReadError plus
HTTP status in {429, 500, 502, 503, 504} — and retries those with bounded
exponential backoff. Any OTHER 4xx is a contract/auth error: it is raised
immediately with status + response text, never retried.
"""

from __future__ import annotations

import asyncio
import logging
import os
import random

import httpx

logger = logging.getLogger(__name__)

#: HTTP statuses worth retrying — rate-limit + the standard transient 5xx set (L4).
_RETRYABLE_STATUSES: frozenset[int] = frozenset({429, 500, 502, 503, 504})

#: `httpx` exception classes that signal a transient network fault (L4).
_RETRYABLE_EXCEPTIONS: tuple[type[Exception], ...] = (
    httpx.TimeoutException,
    httpx.ConnectError,
    httpx.ReadError,
)

#: Per-specialty Band agent keys are read from `BAND_SPECIALIST_<NAME_UPPER>_KEY`.
_SPECIALIST_NAMES: tuple[str, ...] = (
    "liability",
    "ip",
    "termination",
    "tax",
    "data_privacy",
    "indemnity",
)


class HttpBandClient:
    """One agent's live view of the Band Agent API (base /api/v1/agent, X-API-Key auth).

    Satisfies the `BandClient` Protocol from `band.client`. A single persistent
    `httpx.AsyncClient` is held for connection reuse across calls; close it with
    `await client.aclose()` (or use the instance as an async context manager) when
    the agent is done.

    Args:
        api_key: This agent's Band API key (sent as the `X-API-Key` header).
        base_url: Band Agent API base URL; defaults to the live production base.
        timeout: Per-request timeout in seconds (default 20.0, matching the spike).
        max_retries: Max retry attempts for transient failures (default 3).
    """

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://app.band.ai/api/v1/agent",
        *,
        timeout: float = 20.0,
        max_retries: int = 3,
    ) -> None:
        if not api_key or not api_key.strip():
            raise ValueError("HttpBandClient requires a non-empty Band api_key.")
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._max_retries = max_retries
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            headers={"X-API-Key": api_key, "Content-Type": "application/json"},
            timeout=timeout,
        )

    # -- lifecycle -----------------------------------------------------------

    async def aclose(self) -> None:
        """Close the underlying HTTP connection pool."""
        await self._client.aclose()

    async def __aenter__(self) -> HttpBandClient:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()

    # -- core request with L4 retry predicate --------------------------------

    async def _request(self, method: str, path: str, **kw: object) -> httpx.Response:
        """Issue one Band API call, retrying ONLY transient faults.

        Retries `httpx` TimeoutException/ConnectError/ReadError and HTTP responses
        whose status is in `_RETRYABLE_STATUSES` ({429,500,502,503,504}), with
        bounded exponential backoff + jitter. A non-retryable >= 400 response is
        raised immediately as `httpx.HTTPStatusError` carrying status + body text.
        Other (non-retryable) network errors propagate on the final attempt.

        Returns:
            The successful `httpx.Response` (status < 400).
        """
        last_exc: Exception | None = None
        for attempt in range(self._max_retries + 1):
            try:
                response = await self._client.request(method, path, **kw)  # type: ignore[arg-type]
            except _RETRYABLE_EXCEPTIONS as exc:
                last_exc = exc
                if attempt < self._max_retries:
                    await self._backoff(attempt)
                    continue
                raise
            else:
                if response.status_code < 400:
                    return response
                if (
                    response.status_code in _RETRYABLE_STATUSES
                    and attempt < self._max_retries
                ):
                    await self._backoff(attempt)
                    continue
                # Non-retryable 4xx (or exhausted retries): fail loudly with body.
                raise httpx.HTTPStatusError(
                    f"{method} {path} → {response.status_code}: {response.text}",
                    request=response.request,
                    response=response,
                )
        # Unreachable: the loop either returns or raises. Guard for type-checkers.
        assert last_exc is not None  # noqa: S101 — invariant guard
        raise last_exc

    @staticmethod
    async def _backoff(attempt: int) -> None:
        """Sleep with bounded exponential backoff + jitter before a retry."""
        delay = min(2.0**attempt, 8.0) + random.uniform(0.0, 0.25)
        await asyncio.sleep(delay)

    # -- BandClient surface (ported verbatim from spikes/band_room.py) --------

    async def me(self) -> dict:
        """Return this agent's identity dict: {id, handle, name, ...}."""
        response = await self._request("GET", "/me")
        return response.json()["data"]

    async def list_peers(self) -> list[dict]:
        """Return the agent's discoverable same-owner pool as [{id,handle,name}].

        Uses GET /peers — Band's discovery endpoint, which lists other agents (plus
        users and global agents) available for recruitment. The same-owner agents
        are visible here automatically without an explicit contact relationship,
        whereas GET /contacts only covers mutually-consented cross-boundary links;
        /peers is therefore the right source for the same-owner pool.

        Each Band entry is normalized to exactly {id, handle, name}; a missing
        handle/name defaults to "" and the id respectively. /peers lists peers
        available for recruitment and so does not include this agent; any entry
        matching this agent's own id is filtered out defensively.
        """
        my_id = (await self.me()).get("id")
        response = await self._request("GET", "/peers")
        peers = response.json().get("data") or []
        result: list[dict] = []
        for peer in peers:
            pid = peer.get("id")
            if pid is None or pid == my_id:
                continue
            result.append(
                {
                    "id": pid,
                    "handle": peer.get("handle") or "",
                    "name": peer.get("name") or pid,
                }
            )
        return result

    async def list_contacts(self) -> list[dict]:
        """Return ESTABLISHED contacts as [{id,handle,name}] (GET /contacts).

        Distinct from `list_peers`: peers are auto-visible same-owner siblings;
        contacts are mutually-consented relationships, which on Band may cross
        owner boundaries. The endpoint returns a flat `data` array of contact
        records (each `{handle, id, name, type, ...}`; `handle` has no `@` prefix,
        `name` is nullable).

        Each entry is normalized to exactly {id, handle, name}; a missing handle
        defaults to "" and a missing/null name defaults to the id. Entries without
        an id are skipped defensively.
        """
        response = await self._request("GET", "/contacts")
        contacts = response.json().get("data") or []
        result: list[dict] = []
        for contact in contacts:
            cid = contact.get("id")
            if cid is None:
                continue
            result.append(
                {
                    "id": cid,
                    "handle": contact.get("handle") or "",
                    "name": contact.get("name") or cid,
                }
            )
        return result

    async def add_contact(self, handle: str) -> dict:
        """Send a contact request by handle (POST /contacts/add).

        Band resolves the handle and either creates a new request or, if an inverse
        request from that party was already pending, auto-accepts it. The response
        `data` carries `{id, status}` where status is `"pending"` (new request) or
        `"approved"` (auto-accepted). The request body is the bare `{"handle": ...}`
        documented for this endpoint (no wrapper).

        Returns:
            A dict with at least `{"status": "pending"|"approved"}`; the contact/
            request id is surfaced as `"id"` and the raw Band `data` payload is
            preserved under `"raw"` for callers that need the full response.
        """
        try:
            response = await self._request(
                "POST", "/contacts/add", json={"handle": handle}
            )
        except httpx.HTTPStatusError as exc:
            # 409 = already contacts: idempotent success (the relationship exists),
            # which is exactly what the caller wants before recruiting the agent.
            if exc.response.status_code == 409:
                return {"status": "approved", "id": None, "raw": {"conflict": exc.response.text}}
            raise
        data = response.json().get("data") or {}
        return {
            "status": data.get("status"),
            "id": data.get("id"),
            "raw": data,
        }

    async def list_contact_requests(self) -> list[dict]:
        """Return incoming pending contact requests (GET /contacts/requests).

        Band's response nests two directions under `data`: `received` (always
        filtered to pending) and `sent`. This returns only the RECEIVED requests —
        the ones this agent can act on. Each Band `ReceivedContactRequest` carries
        `{from_handle, from_name, id (request id), inserted_at, status, message}`;
        note there is no separate sender-agent id field, so `from_id` is left None
        unless Band supplies one.

        Each request is normalized to include at least `{from_id, from_handle}`,
        plus `request_id`, `from_name`, `status`, and `message` for convenience.
        A missing from_handle defaults to "".
        """
        response = await self._request("GET", "/contacts/requests")
        data = response.json().get("data") or {}
        received = data.get("received") or []
        result: list[dict] = []
        for req in received:
            result.append(
                {
                    "from_id": req.get("from_id"),
                    "from_handle": req.get("from_handle") or "",
                    "from_name": req.get("from_name"),
                    "request_id": req.get("id"),
                    "status": req.get("status"),
                    "message": req.get("message"),
                }
            )
        return result

    async def respond_to_contact_request(self, handle: str, action: str) -> dict:
        """Approve or reject an incoming contact request (POST /contacts/requests/respond).

        For a request this agent RECEIVED, `handle` is the requester's handle and
        `action` is `"approve"` or `"reject"`. The documented body is the bare
        `{"handle": ..., "action": ...}` (no wrapper); Band also accepts a
        `request_id` in place of `handle`, but this surface keys off the handle.

        The response `data` carries `{id, status}` where status is one of
        `"approved"`/`"rejected"` (or `"cancelled"`).

        Returns:
            A dict with at least `{"status": ...}`; the request id is surfaced as
            `"id"` and the raw Band `data` payload is preserved under `"raw"`.
        """
        response = await self._request(
            "POST",
            "/contacts/requests/respond",
            json={"handle": handle, "action": action},
        )
        data = response.json().get("data") or {}
        return {
            "status": data.get("status"),
            "id": data.get("id"),
            "raw": data,
        }

    async def create_room(self, title: str = "") -> str:
        """Create a chat room (this agent becomes owner); return its chat id.

        The body REQUIRES the `{"chat": {...}}` wrapper — a bare `{}` 422s (the
        docs example is wrong; verified live in the spike).
        """
        response = await self._request(
            "POST", "/chats", json={"chat": {"title": title}}
        )
        return response.json()["data"]["id"]

    async def add_participant(self, room_id: str, participant_id: str) -> None:
        """Add another agent (by its agent id) as a participant in `room_id`.

        Idempotent: a 409 means the agent is already in the room — the desired state
        — so it's swallowed rather than raised (e.g. the room creator's owner account
        is auto-added, or an agent is invited twice)."""
        try:
            await self._request(
                "POST",
                f"/chats/{room_id}/participants",
                json={"participant": {"participant_id": participant_id}},
            )
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code != 409:
                raise

    async def post_message(
        self, room_id: str, content: str, mentions: list[dict] | None = None
    ) -> dict:
        """Post a message to `room_id`, @mentioning `mentions` (drives routing).

        Args:
            room_id: Target chat id.
            content: Human-readable message text (typically prefixed with @Name).
            mentions: Recipients as `[{"id", "handle", "name"}, ...]`; the `id`
                fields drive Band's delivery routing. Defaults to no mentions.

        Returns:
            The posted-message data dict (includes `id` and `recipients`).
        """
        response = await self._request(
            "POST",
            f"/chats/{room_id}/messages",
            json={"message": {"content": content, "mentions": mentions or []}},
        )
        return response.json()["data"]

    async def get_next_message(self, room_id: str) -> dict | None:
        """Return the oldest unprocessed message addressed to this agent, or None.

        Band returns `{"data": null}` (not a 404) when the queue is empty; that
        maps to `None`.
        """
        response = await self._request("GET", f"/chats/{room_id}/messages/next")
        return response.json().get("data")

    async def get_context(self, room_id: str) -> list[dict]:
        """Return all messages in `room_id` @mentioning this agent (shared context)."""
        response = await self._request("GET", f"/chats/{room_id}/context")
        return response.json().get("data") or []

    async def mark_processed(self, room_id: str, message_id: str) -> None:
        """Mark a message processed so the agent's queue advances (best-effort).

        Pure queue hygiene: an empty body 422s, so we send a minimal `{}`. Because
        a hygiene blip must never abort the bidding loop, ANY 4xx on THIS call is
        logged at WARNING and swallowed (never raised). Transient faults still get
        the normal L4 retry via `_request`; only a non-retryable 4xx is downgraded.
        """
        try:
            await self._request(
                "POST", f"/chats/{room_id}/messages/{message_id}/processed", json={}
            )
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if 400 <= status < 500:
                logger.warning(
                    "mark_processed best-effort skip — room=%s message=%s → %s: %s",
                    room_id,
                    message_id,
                    status,
                    exc.response.text,
                )
                return
            raise  # 5xx that exhausted retries: surface it.


def make_http_band_client(api_key: str) -> HttpBandClient:
    """Construct an `HttpBandClient` for `api_key` against the live Band API base."""
    return HttpBandClient(api_key)


def specialist_band_keys() -> dict[str, str]:
    """Read per-specialty Band agent keys from the environment.

    Looks up `BAND_SPECIALIST_<NAME_UPPER>_KEY` for each known specialty
    (liability, ip, termination, tax, data_privacy, indemnity) and returns a
    `{specialty_name: key}` mapping containing ONLY the specialties whose key is
    set to a non-empty (stripped) value. Specialties with a missing or blank key
    are omitted, so the caller can register exactly the specialists it has keys for.

    Returns:
        Mapping of specialty name → Band API key, for set keys only.
    """
    keys: dict[str, str] = {}
    for name in _SPECIALIST_NAMES:
        value = os.environ.get(f"BAND_SPECIALIST_{name.upper()}_KEY", "").strip()
        if value:
            keys[name] = value
    return keys
