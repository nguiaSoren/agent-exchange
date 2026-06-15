# Replay Visualizer — Build Contract (the seam)

> Day-6 task: *"Record each job's room + transactions; replay in a standalone
> dependency-free HTML viewer."* Doubles as a §7 hidden-depth artifact + makes the
> demo video trivial to cut.

Every engineer codes against THIS file. It is already validated end-to-end: a real
golden replay produced from the real sim lives at
`data/replays/sample-contract-audit-seeded-liar.replay.json` (39 events, all 10 event
types, the seeded liar caught → $0). **Build and test against that file.**

---

## 0. The big idea

The live UI is driven entirely off an 11-name SSE event stream reduced by
`web/lib/runState.ts → applyEvent(state, ev)`. **A replay file is just that exact event
stream, normalized + timestamped + serialized.** So:

- the **recorder** taps the server's `run_job(...)` generator, normalizes stage events
  to the UI vocabulary, and writes one self-describing JSON file per job;
- the **viewer** is a single dependency-free HTML file whose reducer is a 1:1 vanilla
  port of `applyEvent`. Feed it `events[0..cursor]` and it renders that frame.

No React, no bundler, no network, no MCP. Plain `<script>`/`<style>` in one `.html`.

---

## 1. Replay file format — `agent-exchange.replay/v1`

Reference instance: `data/replays/sample-contract-audit-seeded-liar.replay.json`.

```jsonc
{
  "schema": "agent-exchange.replay/v1",
  "job_id": "sim-contract-audit-seeded-liar",   // stable id, used for output filenames
  "kind": "contract-audit",                      // "contract-audit" | "nda-review"
  "mode": "sim",                                 // "sim" | "live"
  "title": "Acme MSA — clause audit",
  "budget_usd": 0.20,
  "recorded_at": "2026-06-13T00:00:00Z",         // ISO-8601 wall clock, human "when"
  "seed": 1,
  "totals": {                                    // mirror of the terminal `done` payload (nullable)
    "gate_passed": false, "pay_fraction": 0.0,
    "total_settled_usd": 0.0, "total_withheld_usd": 0.115,
    "catch_summary": "1 fabricated claim(s) caught and withheld (6 claims graded)"
  },
  "tx_links": [                                  // settle events that produced a tx (may be [])
    { "worker": "...", "tx_hash": "0x...", "explorer": "https://sepolia.basescan.org/tx/0x..." }
  ],
  "events": [
    { "seq": 0, "t_offset_ms": 0.0, "type": "document", "data": { ... } },
    { "seq": 1, "t_offset_ms": 1.2, "type": "stage",    "data": { "name": "Discover", "status": "active" } }
    // ...
  ]
}
```

**`events[].type`** is one of exactly these 11 (same names as the SSE contract):
`document, stage, pool, bid, hire, room_message, finding, settle, receipt, done, error`.

**`events[].data`** is the payload VERBATIM from `run_job`, with ONE transform applied by
the recorder to `stage` events only (see §2). Payload shapes are authoritative in
`web/lib/events.ts` (`DocumentEvent`, `PoolEvent`, `BidEvent`, `HireEvent`,
`RoomMessageEvent`, `FindingEvent`, `SettleEvent`, `ReceiptEvent`, `DoneEvent`,
`ErrorEvent`) and in the `run_job` docstring in `server/app.py`. Do not reshape them.

**`seq`** is a 0-based monotonic index. **`t_offset_ms`** is ms since the first event
(fidelity only; the player paces on its own — see §5). The seeded-liar run is
near-instant so offsets are tiny — that is expected and fine.

---

## 2. The ONE transform: stage normalization (recorder's job)

`run_job` yields stage events in SERVER vocabulary; the UI reducer + `mockRun.ts` use UI
vocabulary. The recorder maps stage events at capture time so a replay file is identical
in shape to what `applyEvent` already consumes. Pass every other event type through
untouched.

```
name:  discover→Discover  bid→Bid  hire→Hire  collaborate→Work
       verify→Verify  settle→Settle  done→Done
status: start→active   end→done
```

(The UI's full ordered stage list is `["Post","Discover","Bid","Hire","Work","Verify",
"Settle","Done"]`. `Post` is never emitted by the server — it stays `pending`. That is
correct; do not synthesize it.)

---

## 3. File layout & ownership (disjoint — parallel-safe)

```
server/replay_recorder.py        ← AGENT-RECORDER  (+ minimal, optional tee in server/app.py)
web/replay/src/reducer.js        ← AGENT-REDUCER
web/replay/src/view.js           ← AGENT-VIEW
web/replay/src/styles.css        ← AGENT-VIEW
web/replay/src/player.js         ← AGENT-PLAYER
web/replay/shell.html            ← AGENT-PLAYER
tools/build_replay_viewer.py     ← AGENT-BUILD   → emits web/public/replay_viewer.html
```

Build output (BUILD makes these; do not hand-edit):
- `web/public/replay_viewer.html` — generic viewer (drag-drop / file-picker loader).
- `web/public/replay-<job_id>.html` — a chosen replay inlined (double-clickable, file://).

---

## 4. JS interface contract (no modules — one global namespace `RV`)

Everything attaches to `window.RV`. No `import`/`export`, no build tooling. The BUILD
step concatenates the source files into `<script>` blocks in order:
`reducer.js`, then `view.js`, then `player.js`.

### AGENT-REDUCER — `reducer.js`
A faithful vanilla port of `web/lib/runState.ts`. Exposes:
- `RV.initialState() -> state` — mirror `initialState()` exactly (same fields; use a
  plain object/array/Set as there). The seeded stage list = the 8-name `STAGE_ORDER`,
  each `{name, status:"pending"}`.
- `RV.applyEvent(state, ev) -> state` — mirror `applyEvent()` exactly. `ev` is
  `{type, data}` (a replay event minus `seq`/`t_offset_ms`). MUST be pure (return a new
  state; never mutate the input) so the player can recompute any frame by folding.
- `RV.settledTotals(settlements) -> {settled, withheld}` — port the helper.

Read `web/lib/runState.ts` AND `web/components/StageBar.tsx` to confirm status values
(`active`/`done`/`error`/`pending`). Self-verify with Node against the golden file (see
§6).

### AGENT-VIEW — `view.js` + `styles.css`
Exposes ONE pure, idempotent renderer:
- `RV.renderApp(mountEl, state, meta) -> void` — given a `RunState` snapshot and `meta`
  (the replay header minus `events`), (re)render the whole panel view into `mountEl`. Must
  be safe to call every frame (clear + rebuild, or diff — your call; simplicity wins).

Panels to render, faithful in CONTENT to the React components (read them for fidelity —
not pixel-identical, this is a clean vanilla storyboard):
1. **Header** — title, kind, mode badge, budget. (cf. `Dashboard.tsx`)
2. **StageBar** — the 8 stages as a stepper; `active` lit, `done` checked, `pending`
   dim, `error` red. (cf. `StageBar.tsx`)
3. **BidFeed** — each bid: worker, price_usd, relevance, reputation (stars). Mark hired
   vs declined once `state.hire` exists. (cf. `BidFeed.tsx`)
4. **WorkRoom** — the room transcript: `state.room` lines (sender + content). (cf.
   `WorkRoom.tsx`)
5. **Findings / Verify** — each graded finding: worker, clause_ref, claim, verdict
   (✓ confirmed / ~ partial / ✗ unsupported), confidence, evidence_quote. The
   **unsupported** one is the caught lie — make it unmistakable. (cf. `VerifyPanel.tsx`)
6. **SettleBar** — per-worker settle rows: authorized vs settled, status, tx link
   (→ `meta.tx_links` / event `tx_hash` → Basescan) or a clear "$0 · WITHHELD" when
   `settled_usd == 0`. (cf. `SettleBar.tsx`)
7. **Receipt** — signer, signature (truncated), deliverable_hash.
8. **HERO banner** — drive off `state.done`: big `total_settled_usd` vs
   `total_withheld_usd` + `catch_summary`. THIS is the headline ("$0 paid for fabricated
   work — 1 fabricated claim caught & withheld"). Show prominently when `state.done`.

Provider logos / neon arena are OUT of scope — keep it clean and dependency-free. Own
your CSS class vocabulary end-to-end; namespace panel classes `rv-*`. Do not use
`rv-ctl-*` (reserved for the player). Dark, legible, screen-recording-friendly. Cite the
real Basescan base `https://sepolia.basescan.org/tx/<hash>` for tx links.

### AGENT-PLAYER — `player.js` + `shell.html`
`shell.html` is the HTML skeleton with these exact hooks:
- `<div id="rv-app"></div>` — VIEW's mount point.
- `<div id="rv-controls"></div>` — player builds its transport UI here.
- `<div id="rv-drop"></div>` — drag-drop / file-picker zone (shown when no data loaded).
- `<script id="rv-data" type="application/json">null</script>` — the inline-data slot
  (BUILD replaces `null` with a replay object; `null` ⇒ show the loader).
- Slot comments for BUILD to fill, each on its own line, EXACTLY:
  `<!-- @@STYLES@@ -->`, `<!-- @@REDUCER@@ -->`, `<!-- @@VIEW@@ -->`, `<!-- @@PLAYER@@ -->`.

`player.js` owns the timeline engine + loader. Responsibilities:
- On load: read `#rv-data`. If it parses to a non-null replay → load it. Else show
  `#rv-drop` and accept a dropped/picked `.json` file (parse, validate `schema`
  starts with `agent-exchange.replay/`).
- Maintain `cursor` ∈ `[-1 .. events.length-1]`. Current frame state =
  `events.slice(0, cursor+1).reduce(RV.applyEvent, RV.initialState())`. After any cursor
  change call `RV.renderApp(document.getElementById('rv-app'), state, meta)`.
- Transport in `#rv-controls`: ◀ step-back, ▶/⏸ play-pause, ▶▶ step-forward, a scrubber
  `<input type=range>` over events, speed toggle (0.5×/1×/2×/4×), and a **"Jump to the
  catch"** button that advances to the first `finding` with `verdict==="unsupported"`.
- Pacing: play advances the cursor on a timer. Use EVEN beats keyed to event type (stage
  transitions linger ~700ms; bid/finding/room ~350ms; settle ~600ms) × speed — NOT the
  raw `t_offset_ms` (sim offsets are sub-ms). Keep it watchable for a screen recording.
- Namespace your CSS/classes `rv-ctl-*` and keep player CSS inline in `shell.html`
  (inside a `<style>`); VIEW owns `rv-*` panel styling via `styles.css`.

### AGENT-BUILD — `tools/build_replay_viewer.py`
Pure-stdlib Python. Two modes:
- `python tools/build_replay_viewer.py` → assemble `web/public/replay_viewer.html` by
  reading `web/replay/shell.html` and replacing the four `@@...@@` slots with the file
  contents (STYLES←`styles.css` wrapped in `<style>`, REDUCER/VIEW/PLAYER←the `.js`
  wrapped in `<script>`). Leave `#rv-data` as `null`.
- `python tools/build_replay_viewer.py --inline data/replays/<f>.replay.json [--out PATH]`
  → same assembly, but also replace the `#rv-data` body `null` with the replay JSON
  (json.dumps, safely — escape `</script`). Default out: `web/public/replay-<job_id>.html`.
  The result must work from `file://` with no server.
Fail loudly if a slot or source file is missing. Print the output path + byte size.

---

## 5. Playback model (shared mental model)

State is a pure fold. The player never mutates panel state directly — it sets `cursor`,
recomputes by folding `applyEvent` over `events[0..cursor]`, and calls `renderApp`. This
makes scrubbing backward trivial and keeps the reducer the single source of truth.

---

## 6. Self-verification each engineer runs before declaring done

- **REDUCER:** a tiny Node script that folds the golden file's `events` through
  `RV.initialState`/`RV.applyEvent` and asserts the final state matches the golden
  `totals` (e.g. `state.done.total_withheld_usd === 0.115`, `state.done.gate_passed ===
  false`, `state.findings.filter(f=>f.verdict==='unsupported').length === 1`,
  `state.settlements.length === 4`). `node --check reducer.js` must pass.
- **VIEW / PLAYER:** `node --check` each `.js`. Player additionally: confirm the cursor
  fold + `renderApp` interface match this spec (no runtime DOM needed for the check).
- **BUILD:** run both modes against the golden file; assert outputs exist, contain no
  residual `@@...@@` slots, and the `--inline` output contains the embedded job_id.
- **RECORDER:** run it in sim; assert it reproduces a file equal in shape to the golden
  (same event types, same `totals`, stage events already normalized).

Visual correctness (does it LOOK right) is Soren's call — none of us can render a browser.
Make the artifact open cleanly and read clearly; he signs off.

---

## 7. Recorder details (AGENT-RECORDER)

- `server/replay_recorder.py`: a `record_run(kind, mode, *, document="", budget_usd=0.20)
  -> dict` coroutine that drives `run_job` (import from `server/app.py`; add `server/`
  and `src/` to `sys.path` as `app.py` does), normalizes stage events per §2, assembles
  the `agent-exchange.replay/v1` dict, and a `write_replay(replay, out_dir="data/replays")`
  that writes `<job_id>.replay.json`. Provide a `__main__` CLI:
  `python server/replay_recorder.py --kind contract-audit --mode sim [--out DIR]`.
- `job_id`: for sim use `sim-<kind>-seeded-liar`; for live use `live-<kind>-<short ts>`
  (caller passes a timestamp — do NOT call `Date.now()`-equivalents that break
  determinism in tests; `time.time()` in the CLI entrypoint is fine).
- `tx_links`: build from `settle` events that have a non-null `tx_hash`, with
  `explorer = "https://sepolia.basescan.org/tx/" + tx_hash`. May be `[]` (the seeded-liar
  run pays nothing → no tx; that is correct and expected).
- OPTIONAL non-invasive server tee: in `server/app.py`, if `os.getenv("REPLAY_RECORD_DIR")`
  is set, tee each `/api/run`'s events into a replay file in that dir. Keep it strictly
  additive — never change existing `/api/run` behavior or break the 117/117 offline tests.
- Replace the throwaway `tools/_dump_golden_replay.py` with the real recorder, and
  regenerate the golden file so it stays the canonical fixture (keep the same path,
  `job_id`, and `recorded_at` so it's stable).
```
