"""Band spike — two same-owner agents, one room, an @mention routed A→B + shared-context read-back.

Proves Band's load-bearing primitives on the REAL Agent API:
discovery (each agent's identity), rooms (create + add participant), @mention routing
(A posts → B receives), and shared context (B rehydrates the room). This is the same
machinery the marketplace uses when a hired team collaborates in a job room.

Band Agent API (from the docs):
  base    https://app.band.ai/api/v1/agent     auth header  X-API-Key: <agent_key>
  GET   /me                                    → {data:{id,handle,name,...}}
  POST  /chats                       (body {}) → {data:{id,...}}            (creator = owner)
  POST  /chats/{id}/participants               → add {participant:{participant_id:<agent id>}}
  POST  /chats/{id}/messages                   → {message:{content:"@Name ...", mentions:[{id,handle,name}]}}
  GET   /chats/{id}/messages/next              → next unprocessed message for the caller
  GET   /chats/{id}/context                    → all messages @mentioning the caller
  POST  /chats/{id}/messages/{id}/processed    → advance the queue

Prereqs (free, ~5 min, NO hackathon code):
  1. Sign up at app.band.ai.
  2. Create TWO agents under your account; copy each agent's API key (shown once).
  3. Put them in .env as BAND_AGENT_A_KEY and BAND_AGENT_B_KEY.

Run:
    cd agent-exchange && .venv/bin/python spikes/band_room.py
"""

from __future__ import annotations

import os
import sys
import time

import httpx
from dotenv import load_dotenv

load_dotenv()

BASE = os.getenv("BAND_BASE_URL", "https://app.band.ai/api/v1/agent")


def _key(name: str) -> str:
    """Read an API key from env, defensively. A blank value, or a value that is
    actually a stray inline comment / non-ASCII (a .env mis-parse), counts as unset."""
    v = os.environ.get(name, "").strip()
    if not v or v.startswith("#") or not v.isascii() or " " in v:
        return ""
    return v


A_KEY, B_KEY = _key("BAND_AGENT_A_KEY"), _key("BAND_AGENT_B_KEY")

if not A_KEY or not B_KEY:
    sys.exit(
        "Set BAND_AGENT_A_KEY and BAND_AGENT_B_KEY in .env — two agents under one "
        "app.band.ai account (each agent has its own API key, shown once at creation). "
        "Keep .env comments on their own lines (an inline comment on a blank key is "
        "read as the value)."
    )


def _req(method: str, path: str, key: str, **kw) -> dict:
    """One Band API call. Surfaces errors LOUDLY (never swallow — Band 0-docs lesson)."""
    headers = {"X-API-Key": key, "Content-Type": "application/json"}
    r = httpx.request(method, f"{BASE}{path}", headers=headers, timeout=20.0, **kw)
    if r.status_code >= 400:
        raise RuntimeError(f"{method} {path} → {r.status_code}: {r.text}")
    return r.json()


def me(key: str) -> dict:
    return _req("GET", "/me", key)["data"]


def main() -> None:
    # 1. identities (discovery)
    a, b = me(A_KEY), me(B_KEY)
    print(f"agent A: {a['name']!r}  @{a['handle']}  id={a['id']}")
    print(f"agent B: {b['name']!r}  @{b['handle']}  id={b['id']}")
    if a["id"] == b["id"]:
        sys.exit("A and B resolve to the SAME agent — use two different agents' keys.")

    # 2. A creates a room (A is owner). Body wraps in `chat` (like message/participant);
    #    the docs' `{}` example is wrong — the API requires {"chat": {...}}.
    chat_id = _req("POST", "/chats", A_KEY,
                   json={"chat": {"title": "Agent Exchange — Band spike"}})["data"]["id"]
    print(f"room created by A: {chat_id}")

    # 3. A adds B as a participant (participant_id = B's agent id)
    _req("POST", f"/chats/{chat_id}/participants", A_KEY,
         json={"participant": {"participant_id": b["id"]}})
    print("B added to the room")

    # 4. A posts a message @mentioning B (mentions[].id drives routing; content is human-readable)
    content = f"@{b['name']} please confirm you received this — Band routing + shared-context test."
    posted = _req("POST", f"/chats/{chat_id}/messages", A_KEY,
        json={"message": {
            "content": content,
            "mentions": [{"id": b["id"], "handle": b["handle"], "name": b["name"]}],
        }})["data"]
    recips = [r.get("name") for r in posted.get("recipients", [])]
    print(f"A posted message {posted['id']} → routed to: {recips}")

    # 5. B receives it (poll /messages/next — delivery may be a beat behind the POST)
    received = None
    for _ in range(10):
        nxt = _req("GET", f"/chats/{chat_id}/messages/next", B_KEY).get("data")
        if nxt:
            received = nxt
            break
        time.sleep(1)
    if not received:
        sys.exit("B did not receive the message via /messages/next within 10s.")
    print(f'\n✅ B RECEIVED (routed through Band): from {received.get("sender_name")} — "{received["content"]}"')

    # 6. B rehydrates shared context (all messages @mentioning B)
    ctx = _req("GET", f"/chats/{chat_id}/context", B_KEY).get("data", [])
    latest = ctx[0]["content"] if ctx else "—"
    print(f'✅ B shared-context read-back: {len(ctx)} message(s); latest = "{latest}"')

    # 7. hygiene — B marks it processed so the queue advances (best-effort)
    try:
        _req("POST", f"/chats/{chat_id}/messages/{received['id']}/processed", B_KEY, json={})
        print("B marked the message processed (queue advanced).")
    except Exception as e:  # noqa: BLE001 — best-effort, surfaced not swallowed
        print(f"(mark-processed skipped: {e})")

    print(f"\nDONE — a real message routed A→B through a real Band room ({chat_id}). Box 4 ✓")


if __name__ == "__main__":
    main()
