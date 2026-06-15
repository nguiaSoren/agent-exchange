# Replay Route — Build Contract (v2: reuse the Agent Arena)

> Decision change: the replay viewer must LOOK like the Marketplace UI. We retire the
> standalone vanilla viewer and instead **reuse the existing Next.js Agent Arena** in a
> new `/replay` route, driven by replay files through the SAME `runState` reducer the
> live demo uses. Recorder + `agent-exchange.replay/v1` format are unchanged and reused.

The whole trick (already proven in `web/components/Dashboard.tsx`): demo mode is
`for await (ev of mockRun(req)) dispatch(applyEvent)`. A replay file is the SAME event
stream. So replay = fold `replay.events` through `applyEvent` into a `RunState`, render
`<Arena state={state} />`. Add a scrubber/transport on top.

Reference files (read them):
- `web/components/Dashboard.tsx` — the chrome to mirror (masthead, narrator, JOB strip,
  the dark `.ax-court` Arena section). Your replay page mirrors this layout, swapping the
  "launch console" for a "replay loader + transport bar".
- `web/components/arena/Arena.tsx` — `export function Arena({ state }: { state: RunState; demoMode?: boolean })`.
  Fully state-driven; animations fire on `state.*.length` growth (forward playback ⇒ live-like).
- `web/lib/runState.ts` — `initialState()`, `applyEvent(state, ev)`, `type RunState`.
- `web/lib/events.ts` — `ExchangeEvent`, `DoneEvent`, etc. (replay `events[].data` shapes match these).
- `web/lib/mockRun.ts` — the canned-run pattern your replay source mirrors.
- `data/replays/sample-contract-audit-seeded-liar.replay.json` — a real replay (39 events,
  `agent-exchange.replay/v1`): header fields + `events[]` of `{seq,t_offset_ms,type,data}`.
  The seeded liar (an UNSUPPORTED finding) → gate fails → $0 settled / $0.115 withheld.

Replay files for the browser live in **`web/public/replays/`** (served at `/replays/...`).
The page default-loads `/replays/sim-contract-audit-seeded-liar.replay.json` (override via
`?job=<id>` → `/replays/<id>.replay.json`), and also accepts drag-drop / file-pick of any
replay JSON.

---

## File ownership (parallel-safe)

```
web/lib/useReplay.ts                 ← AGENT-REPLAY-CORE  (+ copy replay JSONs into web/public/replays/)
web/app/replay/page.tsx              ← AGENT-REPLAY-UI
web/components/ReplayDashboard.tsx   ← AGENT-REPLAY-UI
```

UI imports CORE by the exact typed interface below — they build in parallel and compose.

---

## The interface seam — `web/lib/useReplay.ts` (AGENT-REPLAY-CORE owns)

A `"use client"` React hook. No new deps. Uses `initialState`/`applyEvent` from
`@/lib/runState` and types from `@/lib/events`.

```ts
import type { RunState } from "@/lib/runState";
import type { DoneEvent, ExchangeEvent } from "@/lib/events";

export interface ReplayMeta {
  schema: string; job_id: string; kind: string; mode: string;
  title: string; budget_usd: number; recorded_at: string; seed: number;
  totals: DoneEvent | null;
  tx_links: { worker: string; tx_hash: string; explorer: string }[];
}

export interface ReplayController {
  status: "empty" | "loading" | "loaded" | "error";
  error: string | null;
  meta: ReplayMeta | null;
  state: RunState;            // events[0..cursor] folded through applyEvent
  cursor: number;            // -1 .. total-1  (-1 = nothing applied yet)
  total: number;             // events.length
  currentType: string | null;// events[cursor]?.type ?? null
  playing: boolean;
  speed: number;             // one of 0.5 | 1 | 2 | 4

  loadFromUrl: (url: string) => Promise<void>;
  loadFromFile: (file: File) => Promise<void>;
  play: () => void;
  pause: () => void;
  toggle: () => void;
  seek: (i: number) => void;     // clamp to [-1, total-1]
  stepFwd: () => void;
  stepBack: () => void;
  cycleSpeed: () => void;        // 0.5→1→2→4→0.5
  jumpToCatch: () => void;       // cursor = first index where ev.type==='finding' && ev.data.verdict==='unsupported'
  restart: () => void;          // cursor = -1, paused
}

export function useReplay(opts?: { autoloadUrl?: string }): ReplayController;
```

Behavior:
- `state` is a pure fold: `events.slice(0, cursor+1).reduce((s,e)=>applyEvent(s,{type:e.type,data:e.data}), initialState())`.
  Recompute via `useMemo` on `[replay, cursor]`. NEVER mutate.
- `loadFromUrl`/`loadFromFile`: fetch/read JSON, validate `schema` startsWith
  `"agent-exchange.replay/"`, store `{ meta: <header w/o events>, events }`, set
  `cursor = -1`, `playing = false`, `status = "loaded"`. On failure set `status="error"`,
  `error`. `meta` = the replay object minus `events`.
- `autoloadUrl`: if provided, `loadFromUrl(it)` on mount (once).
- `play`: advance `cursor` on a timer; **even beats keyed to the NEXT event's type** —
  `stage`≈700ms, `settle`≈600ms, `bid|finding|room_message`≈350ms, else≈450ms — divided
  by `speed`. Do NOT use `t_offset_ms` (sim offsets are sub-ms). Stop at the end. `play`
  at the end restarts from `-1`. Use `setTimeout` recomputed per step; tolerate speed
  changes mid-play. Clean up timers on unmount and on any manual seek/step/pause.
- Manual `seek/step/jumpToCatch/restart` pause playback.
- Guard everything: empty/short event lists never throw.

Also: **copy** `data/replays/sample-contract-audit-seeded-liar.replay.json` and
`data/replays/sample-nda-review-seeded-liar.replay.json` to
`web/public/replays/sim-contract-audit-seeded-liar.replay.json` and
`web/public/replays/sim-nda-review-seeded-liar.replay.json` (the `sim-*` names the page
loads). Use the `sim-*.replay.json` source files if present (identical content).

---

## The route + page — AGENT-REPLAY-UI owns

`web/app/replay/page.tsx`: a server component that renders `<ReplayDashboard />` inside
the same outer theming Dashboard uses. Read `?job=` via the client component (use
`useSearchParams` inside ReplayDashboard, wrapped in `<Suspense>` as Next requires), OR
keep page.tsx minimal and let ReplayDashboard read the param. Default job id:
`sim-contract-audit-seeded-liar`.

`web/components/ReplayDashboard.tsx` (`"use client"`): mirror `Dashboard.tsx`'s layout and
classes (masthead, narrator, JOB strip, the `02 · THE ARENA` dark `.ax-court` section with
`<Arena state={ctl.state} />`). Replace the launch console with:
1. A **loader**: shown when `status !== "loaded"` — a drop zone + file picker ("drop a
   .replay.json") AND a small list/buttons to load the bundled samples
   (`/replays/sim-contract-audit-seeded-liar.replay.json`,
   `/replays/sim-nda-review-seeded-liar.replay.json`). On error show `ctl.error`.
2. A **transport bar** (when loaded), styled to fit the HUD (reuse `NeonButton`, `Eyebrow`,
   `LiveDot` from `@/components/hud` where natural): ◀ step-back, ▶/⏸ (`ctl.toggle`),
   ▶▶ step-fwd, a range `<input>` scrubber (`min=0 max=total-1`, value `cursor`,
   onChange→`seek`), a speed chip (`ctl.speed×`, click→`cycleSpeed`), a "⏭ Jump to the
   catch" button (`ctl.jumpToCatch`), and a "↻ restart". Show a `cursor+1 / total · <currentType>`
   readout. Badge the mode as "REPLAY" (gold `LiveDot`) instead of "DEMO MODE".
3. Use the narrator block from Dashboard verbatim (driven off `ctl.state.stages`) so the
   story beat shows during scrub/playback.

Pass `ctl.meta?.title` into the JOB strip. The Arena renders `ctl.state` — do not
reimplement any arena visuals.

Keep it a CLIENT component subtree; Arena is already `dynamic(ssr:false)` inside Dashboard
— either reuse that import pattern or import Arena the same way (`dynamic(() => import("@/components/arena").then(m=>m.Arena), { ssr:false })`). Confirm `web/components/arena/index` export or import from `@/components/arena/Arena`.

---

## Verification (the orchestrator runs `npm run build` after both finish)

- CORE: `npx tsc --noEmit` clean for `useReplay.ts` in isolation is hard standalone; instead
  ensure the file type-checks as part of the app build. Self-check: re-read the golden
  replay and confirm your fold logic + jumpToCatch index (first unsupported finding) are
  correct by reasoning against it (the unsupported finding is the `tax` worker's clause-14
  claim). Confirm the two files landed in `web/public/replays/`.
- UI: ensure imports resolve (`@/lib/useReplay`, `@/components/arena`, `@/components/hud`,
  `@/lib/runState`). Mirror Dashboard's class names so it inherits the theme.
- The real gate is `cd web && npm run build` (orchestrator runs it); both agents should
  write code that compiles under Next 14 + TS strict. Avoid `any`; type props.

Do NOT edit `Dashboard.tsx`, `Arena*.tsx`, `runState.ts`, `events.ts`, `mockRun.ts`, or any
other existing file. Only create the files you own.
