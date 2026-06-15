"""Band Agent API client — the `BandClient` interface + an in-memory fake.

`BandClient` is the locked surface every Band-touching piece codes against (the
endpoints proven live in `spikes/band_room.py`). `FakeBandClient` is a faithful
in-memory implementation sharing a `BandWorld` across agents, so the whole bidding
flow (job posted → agents see it via @mention routing → agents post bids → market
collects) is testable offline with ZERO network. The real HTTP impl lives in
`band/http_client.py`.

Routing model the fake reproduces (matching Band): a message is delivered to the
agents whose ids are in its `mentions`; `get_next_message` returns the oldest
unprocessed message that mentions THIS agent and wasn't sent by it.
"""

from __future__ import annotations

import itertools
from typing import Protocol, runtime_checkable


@runtime_checkable
class BandClient(Protocol):
    """One agent's view of the Band Agent API (base /api/v1/agent, X-API-Key auth)."""

    async def me(self) -> dict: ...                                                  # {id, handle, name, ...}
    async def list_peers(self) -> list[dict]: ...                                   # → [{id,handle,name}] same-owner pool (GET /peers, auto-visible, excl. self)
    async def list_contacts(self) -> list[dict]: ...                                # → [{id,handle,name}] ESTABLISHED cross-owner contacts (GET /contacts)
    async def add_contact(self, handle: str) -> dict: ...                           # POST /contacts/add — send request by handle → {"status":"pending"|"approved"}
    async def list_contact_requests(self) -> list[dict]: ...                        # GET /contacts/requests — incoming pending [{from_handle, from_id, ...}]
    async def respond_to_contact_request(self, handle: str, action: str) -> dict: ...  # POST /contacts/requests/respond — action "approve"|"reject"
    async def create_room(self, title: str = "") -> str: ...                        # → chat_id
    async def add_participant(self, room_id: str, participant_id: str) -> None: ...
    async def post_message(self, room_id: str, content: str, mentions: list[dict]) -> dict: ...  # mentions=[{id,handle,name}]
    async def get_next_message(self, room_id: str) -> dict | None: ...
    async def get_context(self, room_id: str) -> list[dict]: ...
    async def mark_processed(self, room_id: str, message_id: str) -> None: ...


class BandWorld:
    """Shared in-memory state for a set of FakeBandClients (one simulated Band)."""

    def __init__(self) -> None:
        self.rooms: dict[str, dict] = {}  # room_id -> {"participants": set[str], "messages": list[dict]}
        self.agents: dict[str, dict] = {}  # agent_id -> {"handle": str, "name": str, "owner": str}
        self.contacts: dict[str, set[str]] = {}  # agent_id -> set of ESTABLISHED contact ids (mutual)
        self.contact_requests: list[dict] = []    # pending requests: [{"from_id","to_id","from_handle"}]
        self._room_seq = itertools.count(1)
        self._msg_seq = itertools.count(1)

    def new_room_id(self) -> str:
        return f"room-{next(self._room_seq)}"

    def new_msg_id(self) -> str:
        return f"msg-{next(self._msg_seq)}"


class FakeBandClient:
    """In-memory `BandClient` for one agent, sharing a `BandWorld` with others."""

    def __init__(
        self, agent_id: str, handle: str, name: str, world: BandWorld, *, owner: str = "self"
    ) -> None:
        self.agent_id = agent_id
        self.handle = handle
        self.name = name
        self.world = world
        self.owner = owner  # same-owner peers share this; a different owner needs a contact
        self._processed: set[str] = set()  # msg ids THIS agent has marked processed
        # Register self into the shared world so same-owner peers are discoverable.
        self.world.agents[self.agent_id] = {
            "handle": self.handle, "name": self.name, "owner": owner,
        }

    async def me(self) -> dict:
        return {"id": self.agent_id, "handle": self.handle, "name": self.name}

    async def list_peers(self) -> list[dict]:
        """Same-owner pool: every OTHER agent sharing this owner in the world, id-ordered.

        Mirrors Band `GET /peers` — same-owner siblings are auto-visible with no contact
        needed. Peers are scoped to THIS client's `owner`; agents with a different owner
        require an established contact (see `list_contacts`)."""
        return [
            {"id": aid, "handle": meta["handle"], "name": meta["name"]}
            for aid, meta in sorted(self.world.agents.items())
            if aid != self.agent_id and meta.get("owner") == self.owner
        ]

    def _link(self, a_id: str, b_id: str) -> None:
        """Add the mutual established-contact edge between two agents."""
        self.world.contacts.setdefault(a_id, set()).add(b_id)
        self.world.contacts.setdefault(b_id, set()).add(a_id)

    async def list_contacts(self) -> list[dict]:
        """Established cross-owner contacts (mirrors `GET /contacts`), id-ordered.

        Distinct from `list_peers`: peers are auto-visible same-owner siblings;
        contacts are mutual links explicitly established across owners."""
        return [
            {"id": cid, "handle": meta["handle"], "name": meta["name"]}
            for cid in sorted(self.world.contacts.get(self.agent_id, set()))
            if (meta := self.world.agents.get(cid)) is not None
        ]

    async def add_contact(self, handle: str) -> dict:
        """Send a contact request by handle (mirrors `POST /contacts/add`).

        Resolves the handle, returns `approved` if already linked or if an inverse
        request was pending (auto-accept), otherwise records a pending request."""
        target = next(
            (aid for aid, meta in self.world.agents.items() if meta["handle"] == handle),
            None,
        )
        if target is None:
            return {"status": "error", "reason": "unknown_handle"}
        if target in self.world.contacts.get(self.agent_id, set()):
            return {"status": "approved"}
        # Inverse auto-accept: they already requested us → establish the link.
        for req in self.world.contact_requests:
            if req["from_id"] == target and req["to_id"] == self.agent_id:
                self._link(self.agent_id, target)
                self.world.contact_requests.remove(req)
                return {"status": "approved"}
        self.world.contact_requests.append(
            {"from_id": self.agent_id, "to_id": target, "from_handle": self.handle}
        )
        return {"status": "pending"}

    async def list_contact_requests(self) -> list[dict]:
        """Incoming pending requests addressed to this agent (mirrors `GET /contacts/requests`)."""
        return [
            {"from_id": req["from_id"], "from_handle": req["from_handle"]}
            for req in self.world.contact_requests
            if req["to_id"] == self.agent_id
        ]

    async def respond_to_contact_request(self, handle: str, action: str) -> dict:
        """Approve or reject an incoming request by sender handle (mirrors `POST /contacts/requests/respond`)."""
        req = next(
            (
                r for r in self.world.contact_requests
                if r["from_handle"] == handle and r["to_id"] == self.agent_id
            ),
            None,
        )
        if req is None:
            return {"status": "error", "reason": "no_request"}
        if action == "approve":
            self._link(self.agent_id, req["from_id"])
            self.world.contact_requests.remove(req)
            return {"status": "approved"}
        self.world.contact_requests.remove(req)
        return {"status": "rejected"}

    async def create_room(self, title: str = "") -> str:
        rid = self.world.new_room_id()
        self.world.rooms[rid] = {"participants": {self.agent_id}, "messages": [], "title": title}
        return rid

    async def add_participant(self, room_id: str, participant_id: str) -> None:
        self.world.rooms[room_id]["participants"].add(participant_id)

    async def post_message(self, room_id: str, content: str, mentions: list[dict]) -> dict:
        mid = self.world.new_msg_id()
        msg = {
            "id": mid,
            "chat_room_id": room_id,
            "sender_id": self.agent_id,
            "sender_name": self.name,
            "content": content,
            "metadata": {"mentions": list(mentions)},
            "_mention_ids": [m.get("id") for m in mentions],
        }
        self.world.rooms[room_id]["messages"].append(msg)
        return {"id": mid, "recipients": list(mentions), "success": True}

    async def get_next_message(self, room_id: str) -> dict | None:
        for m in self.world.rooms[room_id]["messages"]:
            if (
                self.agent_id in m["_mention_ids"]
                and m["sender_id"] != self.agent_id
                and m["id"] not in self._processed
            ):
                return dict(m)
        return None

    async def get_context(self, room_id: str) -> list[dict]:
        return [dict(m) for m in self.world.rooms[room_id]["messages"] if self.agent_id in m["_mention_ids"]]

    async def mark_processed(self, room_id: str, message_id: str) -> None:
        self._processed.add(message_id)
