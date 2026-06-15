"""Offline self-test for the SSE event generator — proves the sim-mode lifecycle.

Runs `app.run_job(...)` in ``mode="sim"`` (zero network, zero spend), collects every
emitted ``(event, data)`` pair, and asserts the contract the frontend depends on:

  * the stages fire in order: discover -> bid -> hire -> collaborate -> verify -> settle
    -> done, each as a start/end pair;
  * a ``document`` event is sent first;
  * a ``pool`` event lists the discovered agents;
  * at least one ``bid`` event is emitted;
  * at least one ``finding`` carries a verdict (and the seeded fabrication is caught
    ``unsupported``);
  * at least one ``settle`` event is emitted;
  * a ``receipt`` event carries a signature + deliverable hash;
  * exactly one ``done`` event closes the run with the headline numbers;
  * NO ``error`` event was emitted.

Run:  .venv/bin/python server/_selftest.py
"""

from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import run_job  # noqa: E402


async def _collect(kind: str) -> list[tuple[str, dict]]:
    events: list[tuple[str, dict]] = []
    async for ev in run_job(kind, document="", budget_usd=0.20, requested_mode="sim"):
        events.append(ev)
    return events


def _assert_sequence(events: list[tuple[str, dict]], kind: str) -> None:
    names = [name for name, _ in events]

    # No error frame anywhere.
    errors = [d for n, d in events if n == "error"]
    assert not errors, f"[{kind}] unexpected error event(s): {errors}"

    # document is the very first event.
    assert names[0] == "document", f"[{kind}] first event must be 'document', got {names[0]!r}"
    doc = events[0][1]
    assert doc["kind"] == kind and doc["document_text"], f"[{kind}] document payload incomplete"

    # Stage start/end ordering.
    expected_stages = ["discover", "bid", "hire", "collaborate", "verify", "settle", "done"]
    stage_seq = [(d["name"], d["status"]) for n, d in events if n == "stage"]
    flat: list[tuple[str, str]] = []
    for s in expected_stages:
        flat.append((s, "start"))
        flat.append((s, "end"))
    assert stage_seq == flat, (
        f"[{kind}] stage sequence mismatch.\n  got:      {stage_seq}\n  expected: {flat}"
    )

    # pool with >= 1 agent.
    pools = [d for n, d in events if n == "pool"]
    assert pools and pools[0]["agents"], f"[{kind}] missing/empty pool event"

    # >= 1 bid.
    bids = [d for n, d in events if n == "bid"]
    assert len(bids) >= 1, f"[{kind}] expected >= 1 bid, got {len(bids)}"

    # hire event present.
    hires = [d for n, d in events if n == "hire"]
    assert hires and hires[0]["hired"], f"[{kind}] missing hire event"

    # >= 1 finding carrying a verdict; the seeded fabrication is caught unsupported.
    findings = [d for n, d in events if n == "finding"]
    assert len(findings) >= 1, f"[{kind}] expected >= 1 finding"
    verdicts = {f["verdict"] for f in findings}
    assert verdicts <= {"confirmed", "partial", "unsupported"}, f"[{kind}] bad verdict label"
    assert any(f["verdict"] == "unsupported" for f in findings), (
        f"[{kind}] expected the seeded fabrication to be caught 'unsupported'"
    )

    # >= 1 settle event.
    settles = [d for n, d in events if n == "settle"]
    assert len(settles) >= 1, f"[{kind}] expected >= 1 settle, got {len(settles)}"

    # receipt with signature + hash.
    receipts = [d for n, d in events if n == "receipt"]
    assert receipts, f"[{kind}] missing receipt event"
    assert receipts[0]["signature"].startswith("0x"), f"[{kind}] receipt signature malformed"
    assert receipts[0]["deliverable_hash"].startswith("0x"), f"[{kind}] receipt hash malformed"

    # exactly one done event.
    dones = [d for n, d in events if n == "done"]
    assert len(dones) == 1, f"[{kind}] expected exactly one done, got {len(dones)}"
    done = dones[0]
    # A seeded fabrication -> the no-fabrication gate withholds the whole job.
    assert done["gate_passed"] is False, f"[{kind}] expected the gate to FAIL (fabrication seeded)"
    assert done["total_settled_usd"] == 0.0, f"[{kind}] expected $0 settled on a withheld job"
    assert done["total_withheld_usd"] > 0.0, f"[{kind}] expected a positive withheld amount"


def _print_events(events: list[tuple[str, dict]], kind: str) -> None:
    print(f"\n=== sim run: kind={kind} — {len(events)} events ===")
    for name, data in events:
        if name == "stage":
            print(f"  stage         {data['name']}/{data['status']}")
        elif name == "document":
            print(f"  document      {data['title']!r} ({len(data['document_text'])} chars, "
                  f"budget ${data['budget_usd']})")
        elif name == "pool":
            print(f"  pool          {len(data['agents'])} agents: "
                  f"{[a['name'] for a in data['agents']]}")
        elif name == "bid":
            print(f"  bid           {data['worker']:<20} ${data['price_usd']:.3f}  "
                  f"rel={data['relevance']:.2f}")
        elif name == "hire":
            print(f"  hire          hired={[h['worker'] for h in data['hired']]} "
                  f"strategy={data['strategy']}")
        elif name == "room_message":
            content = (data["content"] or "").replace("\n", " ")
            print(f"  room_message  [{data['sender']}] {content[:70]}")
        elif name == "finding":
            print(f"  finding       {data['worker']:<20} clause {data['clause_ref'] or '-':<4} "
                  f"[{data['verdict']}] conf={data['confidence']:.2f}")
        elif name == "settle":
            print(f"  settle        {data['worker']:<20} auth=${data['authorized_usd']:.3f} "
                  f"settled=${data['settled_usd']:.3f} [{data['status']}] "
                  f"tx={(data['tx_hash'] or '-')[:14]}")
        elif name == "receipt":
            print(f"  receipt       signer={data['signer'][:12]}… "
                  f"hash={data['deliverable_hash'][:14]}…")
        elif name == "done":
            print(f"  done          gate_passed={data['gate_passed']} "
                  f"pay_fraction={data['pay_fraction']} "
                  f"settled=${data['total_settled_usd']} withheld=${data['total_withheld_usd']}")
            print(f"                catch: {data['catch_summary']}")
        elif name == "error":
            print(f"  ERROR         {data['message']}")


def main() -> None:
    for kind in ("contract-audit", "nda-review"):
        events = asyncio.run(_collect(kind))
        _print_events(events, kind)
        _assert_sequence(events, kind)
        print(f"\n  ✓ [{kind}] event sequence OK "
              f"({len([1 for n, _ in events if n == 'finding'])} findings, "
              f"{len([1 for n, _ in events if n == 'settle'])} settles)")
    print("\nALL SELF-TESTS PASSED.")


if __name__ == "__main__":
    main()
