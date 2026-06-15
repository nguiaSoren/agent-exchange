"""Replay recorder — captures a real marketplace job run into a replay file.

Drives `run_job` from server/app.py, normalizes stage events per spec §2, assembles
the agent-exchange.replay/v1 dict, and writes one self-describing JSON file per job.

Usage (CLI):
    python server/replay_recorder.py --kind contract-audit --mode sim [--out DIR]
    python server/replay_recorder.py --kind nda-review --mode sim

For sim, uses fixed recorded_at="2026-06-13T00:00:00Z" and
job_id="sim-<kind>-seeded-liar" so the golden fixture stays stable/reproducible.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time

# ---------------------------------------------------------------------------
# Path bootstrap — add server/ and src/ so `from app import run_job` works
# when this module is run from anywhere (mirrors how app.py does it for src/).
# ---------------------------------------------------------------------------

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SERVER = os.path.join(_ROOT, "server")
_SRC = os.path.join(_ROOT, "src")
for _p in (_SERVER, _SRC):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from app import run_job  # noqa: E402  (must be after path bootstrap)
from agent_exchange.redact import default_policy, redact_obj  # noqa: E402

# ---------------------------------------------------------------------------
# Stage normalization — server vocabulary -> UI vocabulary (spec §2)
# ---------------------------------------------------------------------------

_STAGE_NAME: dict[str, str] = {
    "discover": "Discover",
    "bid": "Bid",
    "hire": "Hire",
    "collaborate": "Work",
    "verify": "Verify",
    "settle": "Settle",
    "done": "Done",
}
_STAGE_STATUS: dict[str, str] = {
    "start": "active",
    "end": "done",
}

_EXPLORER_BASE = "https://sepolia.basescan.org/tx/"


def _normalize(event: str, data: dict) -> tuple[str, dict]:
    """Apply the ONE transform: stage events only (spec §2). Everything else passes through."""
    if event == "stage":
        data = {
            "name": _STAGE_NAME.get(data["name"], data["name"]),
            "status": _STAGE_STATUS.get(data["status"], data["status"]),
        }
    return event, data


# ---------------------------------------------------------------------------
# Core API
# ---------------------------------------------------------------------------


async def record_run(
    kind: str,
    mode: str,
    *,
    document: str = "",
    budget_usd: float = 0.20,
    job_id: str | None = None,
    recorded_at: str | None = None,
) -> dict:
    """Drive `run_job`, normalize events, and return the agent-exchange.replay/v1 dict.

    Args:
        kind: Job kind — "contract-audit" or "nda-review".
        mode: Run mode — "sim" or "live".
        document: Optional document text (empty string → app uses its sample).
        budget_usd: Budget ceiling in USD.
        job_id: Stable identifier for the run. Defaults to:
            sim  → "sim-<kind>-seeded-liar"
            live → "live-<kind>-<short-ts>" (uses recorded_at if provided)
        recorded_at: ISO-8601 wall-clock string for the replay header. Callers
            pass this in so deterministic (sim) runs are stable across invocations.
            The CLI entrypoint uses a fixed value for sim; time.time() for live.
    """
    if recorded_at is None:
        from datetime import datetime, timezone
        recorded_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    if job_id is None:
        if mode == "sim":
            job_id = f"sim-{kind}-seeded-liar"
        else:
            # Derive a short timestamp from recorded_at so the id is deterministic
            # when the caller passes a fixed recorded_at (and does not call hidden clocks).
            short_ts = recorded_at.replace(":", "").replace("-", "").replace("Z", "")[:13]
            job_id = f"live-{kind}-{short_ts}"

    raw_events: list[tuple[str, dict]] = []
    t0 = time.perf_counter()

    async for event, data in run_job(kind, document, budget_usd, mode):
        event, data = _normalize(event, data)
        t_ms = round((time.perf_counter() - t0) * 1000, 1)
        raw_events.append((event, data, t_ms))

    # Build events list (seq = index).
    events: list[dict] = []
    for seq, (ev_type, ev_data, t_ms) in enumerate(raw_events):
        events.append({
            "seq": seq,
            "t_offset_ms": t_ms,
            "type": ev_type,
            "data": ev_data,
        })

    # Pull title + budget_usd from the `document` event (first event).
    title = kind
    actual_budget = budget_usd
    for ev in events:
        if ev["type"] == "document":
            title = ev["data"].get("title", kind)
            actual_budget = ev["data"].get("budget_usd", budget_usd)
            break

    # Pull totals from the `done` event.
    totals: dict | None = None
    for ev in events:
        if ev["type"] == "done":
            totals = dict(ev["data"])
            break

    # tx_links from settle events with a non-null tx_hash.
    tx_links = [
        {
            "worker": ev["data"]["worker"],
            "tx_hash": ev["data"]["tx_hash"],
            "explorer": _EXPLORER_BASE + ev["data"]["tx_hash"],
        }
        for ev in events
        if ev["type"] == "settle" and ev["data"].get("tx_hash")
    ]

    replay = {
        "schema": "agent-exchange.replay/v1",
        "job_id": job_id,
        "kind": kind,
        "mode": mode,
        "title": title,
        "budget_usd": actual_budget,
        "recorded_at": recorded_at,
        "seed": 1,
        "totals": totals,
        "tx_links": tx_links,
        "events": events,
    }
    return replay


def write_replay(replay: dict, out_dir: str = "data/replays", *, redact_policy=None) -> str:
    """Write replay dict to <out_dir>/<job_id>.replay.json; return the path.

    PII is redacted from the replay events (``document`` text, ``room_message``
    content, ``finding`` claim/evidence — every string leaf) BEFORE the JSON is
    written, so the persisted replay never holds PII. The conservative default policy
    leaves the sample MSA/NDA fixtures and on-chain hex addresses byte-identical.
    """
    pol = redact_policy if redact_policy is not None else default_policy()
    replay = redact_obj(replay, pol)  # type: ignore[assignment]
    # Resolve out_dir relative to repo root if it is not absolute.
    if not os.path.isabs(out_dir):
        out_dir = os.path.join(_ROOT, out_dir)
    os.makedirs(out_dir, exist_ok=True)
    job_id = replay["job_id"]
    out_path = os.path.join(out_dir, f"{job_id}.replay.json")
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(replay, fh, indent=2)
    return out_path


# ---------------------------------------------------------------------------
# CLI entrypoint
# ---------------------------------------------------------------------------

def _main() -> None:
    parser = argparse.ArgumentParser(
        description="Record a marketplace job run into a replay file.",
    )
    parser.add_argument(
        "--kind",
        default="contract-audit",
        choices=["contract-audit", "nda-review"],
        help="Job kind (default: contract-audit)",
    )
    parser.add_argument(
        "--mode",
        default="sim",
        choices=["sim", "live"],
        help="Run mode (default: sim)",
    )
    parser.add_argument(
        "--out",
        default="data/replays",
        metavar="DIR",
        help="Output directory (default: data/replays)",
    )
    args = parser.parse_args()

    # For sim, use fixed timestamps so the golden fixture is STABLE/reproducible.
    # For live, use the actual current time.
    if args.mode == "sim":
        recorded_at = "2026-06-13T00:00:00Z"
        job_id = f"sim-{args.kind}-seeded-liar"
    else:
        from datetime import datetime, timezone
        recorded_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        short_ts = recorded_at.replace(":", "").replace("-", "").replace("Z", "")[:13]
        job_id = f"live-{args.kind}-{short_ts}"

    replay = asyncio.run(
        record_run(
            args.kind,
            args.mode,
            budget_usd=0.20,
            job_id=job_id,
            recorded_at=recorded_at,
        )
    )

    out_path = write_replay(replay, out_dir=args.out)

    # For sim contract-audit, also write the canonical "sample-" filename so the
    # golden fixture stays stable (REPLAY_SPEC §3 / task instructions).
    canonical_name = f"sample-{args.kind}-seeded-liar.replay.json"
    if args.mode == "sim":
        out_dir_abs = out_path.rsplit(os.sep, 1)[0]
        canonical_path = os.path.join(out_dir_abs, canonical_name)
        if os.path.basename(out_path) != canonical_name:
            with open(canonical_path, "w", encoding="utf-8") as fh:
                json.dump(replay, fh, indent=2)

    n_events = len(replay["events"])
    totals = replay.get("totals") or {}
    catch_summary = totals.get("catch_summary", "n/a")
    n_tx = len(replay.get("tx_links") or [])
    print(out_path)
    print(f"events={n_events}  catch_summary={catch_summary!r}  tx_links={n_tx}")


if __name__ == "__main__":
    _main()
