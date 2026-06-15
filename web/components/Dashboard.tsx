"use client";

import { useCallback, useEffect, useReducer, useRef, useState } from "react";
import dynamic from "next/dynamic";
import type { ExchangeEvent, JobKind, RunRequest } from "@/lib/events";
import { applyEvent, initialState, type RunState } from "@/lib/runState";
import { runJob, fetchSample, warmBackend, API_BASE } from "@/lib/stream";
import { localSample, mockRun } from "@/lib/mockRun";
import { scrollIntoFullView } from "@/lib/scroll";
import { JobCard } from "./JobCard";
import { Eyebrow, GlitchText, NeonButton, LiveDot, Exchange, Narrator } from "@/components/hud";
import { IntroOverlay } from "./IntroOverlay";
import { BeatCaption } from "./BeatCaption";
import {
  isCinematicParam,
  prefersReducedMotion,
  GATE_LINGER_MS,
  RESEARCH_LINGER_MS,
  CINEMATIC_DELAY_SCALE,
} from "@/lib/cinematic";

// The arena is rendered client-only (ssr:false): its brand logos come from
// @lobehub/icons, whose barrel is not safe to prerender on the server. Lazy +
// client-only keeps that whole subtree out of the static export, and shows a
// calm placeholder ring during load so the layout never jumps.
const Arena = dynamic(() => import("./arena").then((m) => m.Arena), {
  ssr: false,
  loading: () => (
    <div
      className="flex w-full items-center justify-center"
      style={{ aspectRatio: "1 / 1", maxHeight: 480 }}
    >
      <div
        aria-hidden
        className="rounded-full border border-hud-neutral"
        style={{ width: "45%", aspectRatio: "1 / 1", opacity: 0.4 }}
      />
    </div>
  ),
});

/** Banner copy shown when a live run falls back to the recorded real run. */
const FALLBACK_COPY: Record<string, string> = {
  live_busy: "Live backend busy — showing the last real Band-room run.",
  live_cap_reached:
    "Daily live-run budget reached — showing the last real Band-room run.",
  live_unavailable:
    "Live backend warming up — showing the last real Band-room run.",
};

const sleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));

type Action =
  | { kind: "reset" }
  | { kind: "start" }
  | { kind: "event"; ev: ExchangeEvent };

function reducer(state: RunState, action: Action): RunState {
  switch (action.kind) {
    case "reset":
      return initialState();
    case "start": {
      const fresh = initialState();
      fresh.running = true;
      return fresh;
    }
    case "event":
      return applyEvent(state, action.ev);
  }
}

export function Dashboard() {
  const [state, dispatch] = useReducer(reducer, undefined, initialState);

  const [kind, setKind] = useState<JobKind>("contract-audit");
  const [document, setDocument] = useState<string>(
    () => localSample("contract-audit").document_text
  );
  const [budget, setBudget] = useState<number>(12);
  const [demoMode, setDemoMode] = useState<boolean>(true);
  const [loadingSample, setLoadingSample] = useState<boolean>(false);
  // C3: immediate feedback — true from Run press until the first event lands
  const [starting, setStarting] = useState<boolean>(false);

  // ── Live run + recorded fallback ──────────────────────────────────────────
  // A judge-triggered LIVE run (ax:run-live) hits the real backend. On free-tier
  // Render the cold start is ~60-90s, so we show an intentional "spinning up a
  // real Band room…" notice while no event has landed. If the backend returns
  // 429 (busy / cap / unavailable) or errors/times-out, we transparently fall
  // back to the LAST RECORDED real run — same arena, with a clear banner. Never
  // a dead spinner.
  const [liveStarting, setLiveStarting] = useState<boolean>(false);
  // Fallback banner copy (null = no fallback active).
  const [fallbackNote, setFallbackNote] = useState<string | null>(null);

  // ── Cinematic auto-play demo ──────────────────────────────────────────────
  // `cinematic` is the on-rails mode: intro overlay → auto-start the run → beat
  // captions synced to the active stage → linger on the GATE → scroll to the
  // #research finale and linger. Triggered by `?demo=cinematic` (auto) OR the
  // "Watch the cinematic" button. It REUSES the run path (onRun) — never forks.
  const [cinematic, setCinematic] = useState<boolean>(false);
  // Mirror of `cinematic` for the run loop (onRun is a stable useCallback, so it
  // can't read the live `cinematic` state without going stale — the ref can).
  // Lets the run slow down ONLY when it's the cinematic take.
  const cinematicRef = useRef(false);
  useEffect(() => {
    cinematicRef.current = cinematic;
  }, [cinematic]);
  // Mount the intro overlay (the opening beat). Set true when cinematic fires.
  const [introUp, setIntroUp] = useState<boolean>(false);
  const finaleDoneRef = useRef(false);

  const abortRef = useRef<(() => void) | null>(null);
  const runIdRef = useRef(0);
  // Cleanup for the cinematic finale timers (linger → scroll → linger).
  const cleanupRef = useRef<(() => void) | null>(null);

  // Prefill the document when the kind changes. DEMO mode is fully
  // self-contained — it uses the local sample and NEVER touches the network. A
  // deployed sim hitting the localhost backend would trip the browser's
  // "access devices on your local network" permission prompt (and fail), so we
  // only fetch a backend sample on the explicit LIVE path.
  useEffect(() => {
    let cancelled = false;
    setLoadingSample(true);
    (async () => {
      const remote = demoMode ? null : await fetchSample(kind);
      if (cancelled) return;
      const sample = remote ?? localSample(kind);
      setDocument(sample.document_text);
      if (typeof sample.budget_usd === "number") setBudget(sample.budget_usd);
      setLoadingSample(false);
    })();
    return () => {
      cancelled = true;
    };
  }, [kind, demoMode]);

  // The arena section — scrolled fully into view when a run starts.
  const arenaRef = useRef<HTMLElement>(null);

  // Clean up an in-flight stream on unmount.
  useEffect(() => () => abortRef.current?.(), []);

  // Pre-warm the live backend so a judge's click streams in ~1s instead of
  // hitting Render's ~40-90s free-tier cold start (which reads as a frozen
  // "waiting for job"). Ping on mount + every 5 min while the page is open.
  useEffect(() => {
    void warmBackend();
    const id = setInterval(() => void warmBackend(), 5 * 60_000);
    return () => clearInterval(id);
  }, []);

  // The launch console collapses once a run is active so the arena owns the
  // stage; it returns on reset (idle) so a new job can be posted.
  const narratorOn = state.running || state.finished;
  const consoleOpen = !narratorOn;

  // Play the LAST RECORDED real Band-room run through the SAME arena reducer.
  // Triggered when a live run is busy/capped/unavailable or fails on cold start.
  // Reuses the canonical replay schema (web/public/replays/live-real-run.replay.json,
  // produced by a parallel engineer). If the fixture 404s, we fail gracefully —
  // a banner pointing at the cinematic above — never a dead spinner.
  const playRecordedFallback = useCallback(
    async (myRun: number, reason: "live_busy" | "live_cap_reached" | "live_unavailable") => {
      if (runIdRef.current !== myRun) return;
      try {
        const res = await fetch("/replays/live-real-run.replay.json", {
          headers: { Accept: "application/json" },
        });
        if (!res.ok) throw new Error(`replay ${res.status}`);
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        const raw: any = await res.json();
        const events: { type: string; data: unknown }[] = Array.isArray(raw?.events)
          ? raw.events
          : [];
        if (events.length === 0) throw new Error("empty replay");

        // We're now showing the recorded run — clear the spinner, set the banner.
        setStarting(false);
        setLiveStarting(false);
        setFallbackNote(FALLBACK_COPY[reason]);
        dispatch({ kind: "reset" });
        dispatch({ kind: "start" });

        for (const e of events) {
          if (runIdRef.current !== myRun) return;
          await sleep(220);
          if (runIdRef.current !== myRun) return;
          dispatch({ kind: "event", ev: { type: e.type, data: e.data } as ExchangeEvent });
        }
      } catch {
        if (runIdRef.current !== myRun) return;
        // Fixture missing / unreadable: don't spin forever. Surface a calm note
        // that points the judge back at the cinematic demo above.
        setStarting(false);
        setLiveStarting(false);
        setFallbackNote(null);
        dispatch({
          kind: "event",
          ev: {
            type: "error",
            data: {
              message:
                "Live run unavailable right now — watch the cinematic above for the full flow.",
            },
          },
        });
      }
    },
    [],
  );

  // `onRun` accepts an optional override so a LIVE trigger (ax:run-live) can pass
  // the judge's exact {kind, document, mode} synchronously — React state set in
  // the same tick wouldn't be visible to this closure yet. With no override it
  // uses the launch-console state (the Run button path), unchanged.
  const onRun = useCallback(
    async (override?: { kind?: JobKind; document?: string; mode?: "sim" | "live" }) => {
      abortRef.current?.();
      const myRun = ++runIdRef.current;

      const runKind = override?.kind ?? kind;
      const runDoc = override?.document ?? document;
      const isDemo = override?.mode ? override.mode === "sim" : demoMode;

      // C3: show "Assembling" micro-state immediately — before any event lands
      setStarting(true);
      setFallbackNote(null);
      // Live cold-start notice only on the live path (Render spin-up reads ~60-90s).
      setLiveStarting(!isDemo);
      dispatch({ kind: "start" });

      // The console collapses on this render and the arena takes the stage —
      // scroll it FULLY into view (bottom corners + legend) after the relayout
      // paints. Two rAFs so the collapsed layout has settled first.
      requestAnimationFrame(() =>
        requestAnimationFrame(() => scrollIntoFullView(arenaRef.current)),
      );

      const req: RunRequest = {
        kind: runKind,
        document: runDoc,
        budget_usd: budget,
        mode: isDemo ? "sim" : "live",
      };

      try {
        if (isDemo) {
          abortRef.current = null;
          // Cinematic take runs slower so the beat captions are readable.
          const scale = cinematicRef.current ? CINEMATIC_DELAY_SCALE : 1;
          for await (const ev of mockRun(req, scale)) {
            if (runIdRef.current !== myRun) return;
            setStarting(false);
            dispatch({ kind: "event", ev });
          }
        } else {
          const handle = runJob(req);
          abortRef.current = handle.abort;
          // Safety net: if the backend never streams a FIRST event (a stuck cold
          // start or a dead dyno), don't spin forever — abort after the stated
          // cold-start window so the catch below falls back to the recorded run.
          // Pre-warming usually lands the first event in ~1s, so this rarely fires.
          let gotFirst = false;
          const firstEventTimer = setTimeout(() => {
            if (!gotFirst) handle.abort();
          }, 90_000);
          try {
            for await (const ev of handle.events) {
              if (runIdRef.current !== myRun) return;
              // A typed 429 (busy/cap/unavailable) arrives as an error event with
              // `live_status` set BEFORE any stream content — fall back to the
              // recorded real run rather than showing a hard error.
              if (ev.type === "error" && ev.data.live_status) {
                handle.abort();
                await playRecordedFallback(myRun, ev.data.live_status);
                return;
              }
              gotFirst = true;
              clearTimeout(firstEventTimer);
              setStarting(false);
              setLiveStarting(false);
              dispatch({ kind: "event", ev });
            }
          } finally {
            clearTimeout(firstEventTimer);
          }
        }
      } catch (err) {
        if (runIdRef.current !== myRun) return;
        // On the LIVE path, a network/cold-start failure also falls back to the
        // recorded run — never a dead spinner.
        if (!isDemo) {
          await playRecordedFallback(myRun, "live_unavailable");
          return;
        }
        setStarting(false);
        setLiveStarting(false);
        dispatch({
          kind: "event",
          ev: {
            type: "error",
            data: { message: err instanceof Error ? err.message : String(err) },
          },
        });
      }
    },
    // playRecordedFallback is a stable useCallback declared below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [kind, document, budget, demoMode],
  );

  // Landing CTAs ("Watch it run" / "Run the live demo") fire `ax:run-demo` to
  // start the demo exactly like clicking Run — same code path ⇒ the demo plays
  // AND the arena scrolls to the identical position.
  useEffect(() => {
    const handler = () => onRun();
    window.addEventListener("ax:run-demo", handler);
    return () => window.removeEventListener("ax:run-demo", handler);
  }, [onRun]);

  // `ax:run-live` (fired by the "Run it live" section) starts a REAL backend run
  // of the judge's document. It REUSES onRun on the live path — same arena, same
  // stream, same fallback — by passing the doc + kind as a synchronous override
  // and forcing mode:"live". It also flips the masthead badge to LIVE.
  useEffect(() => {
    const handler = (e: Event) => {
      const detail = (e as CustomEvent<{ kind?: JobKind; document?: string }>).detail;
      const liveKind = detail?.kind ?? kind;
      const liveDoc = detail?.document ?? document;
      // Reflect the live choice in the console state (so a later reset/edit reads
      // the same doc) and drive the masthead's LIVE badge.
      if (detail?.kind) setKind(liveKind);
      if (typeof detail?.document === "string") setDocument(liveDoc);
      setDemoMode(false);
      void onRun({ kind: liveKind, document: liveDoc, mode: "live" });
    };
    window.addEventListener("ax:run-live", handler);
    return () => window.removeEventListener("ax:run-live", handler);
  }, [onRun, kind, document]);

  // Start the cinematic: raise the intro overlay. Its lift fires `onLift`, which
  // calls onRun() — so the run starts on the SAME path as the Run button. We
  // also support a `window` event ("ax:cinematic") so a landing CTA can trigger
  // it without prop-drilling.
  const startCinematic = useCallback(() => {
    if (cinematic) return;
    setCinematic(true);
    finaleDoneRef.current = false;
    setIntroUp(true);
  }, [cinematic]);

  // Auto-trigger from `?demo=cinematic` on first mount (ideal for recording).
  useEffect(() => {
    if (isCinematicParam()) startCinematic();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Allow a window event to trigger the cinematic too (parity with ax:run-demo).
  useEffect(() => {
    const handler = () => startCinematic();
    window.addEventListener("ax:cinematic", handler);
    return () => window.removeEventListener("ax:cinematic", handler);
  }, [startCinematic]);

  // The cinematic FINALE: once the run completes, the arena's own effect scrolls
  // the GATE summary into view. We then linger on the GATE, smooth-scroll to the
  // #research proof section, and linger there. Runs once per cinematic run.
  useEffect(() => {
    if (!cinematic || !state.finished || finaleDoneRef.current) return;
    finaleDoneRef.current = true;
    const reduce = prefersReducedMotion();

    const toResearch = setTimeout(() => {
      const research = window.document.getElementById("research");
      if (research) {
        research.scrollIntoView({
          behavior: reduce ? "auto" : "smooth",
          block: "start",
        });
      }
      // After lingering on the finale, drop the beat caption (the run is over).
      const endBeats = setTimeout(() => setCinematic(false), RESEARCH_LINGER_MS);
      cleanupRef.current = () => clearTimeout(endBeats);
    }, GATE_LINGER_MS);

    cleanupRef.current = () => clearTimeout(toResearch);
    return () => cleanupRef.current?.();
  }, [cinematic, state.finished]);

  const onReset = () => {
    runIdRef.current++;
    abortRef.current?.();
    cleanupRef.current?.();
    setStarting(false);
    setLiveStarting(false);
    setFallbackNote(null);
    setCinematic(false);
    setIntroUp(false);
    dispatch({ kind: "reset" });
  };

  return (
    <main className="ax-light ax-stage mx-auto flex min-h-screen max-w-[1240px] flex-col gap-10 px-6 py-12 lg:px-8 lg:py-16">
      {/* ── Masthead ─────────────────────────────────────────────── */}
      <header className="flex flex-wrap items-end justify-between gap-5 border-b border-hud-neutral pb-8">
        <div className="flex items-center gap-4">
          <div className="flex h-11 w-11 items-center justify-center rounded-lg border border-hud-neutral bg-surface-2 text-fg">
            <Exchange size={22} />
          </div>
          <div>
            <Eyebrow live tone="muted">
              LIVE AGENT LABOR MARKET
            </Eyebrow>
            <GlitchText
              as="h1"
              className="mt-1.5 text-[24px] font-black uppercase tracking-[0.04em] text-fg"
            >
              Agent Exchange
            </GlitchText>
            <p className="mt-1.5 max-w-xl font-mono text-[12.5px] leading-relaxed text-fg-muted">
              Agents bid, hire each other, and get paid only when the work is
              proven real.
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2.5 font-mono text-[11px]">
          <span className="inline-flex items-center gap-2 rounded-md border border-hud-neutral bg-surface px-3 py-1.5 text-fg-muted">
            <LiveDot tone={demoMode ? "gold" : "emerald"} size={7} />
            {demoMode
              ? "DEMO MODE"
              : `LIVE · ${API_BASE.replace(/^https?:\/\//, "")}`}
          </span>
          {state.finished && (
            <NeonButton variant="ghost" onClick={onReset} className="text-[11px]">
              reset
            </NeonButton>
          )}
        </div>
      </header>

      {/* ── Narrator: guides the eye through the live run ────────── */}
      <Narrator
        stages={state.stages}
        running={state.running}
        finished={state.finished}
        starting={starting}
      />

      {/* ── Launch console: post a job (collapses once a run is live) ── */}
      {consoleOpen ? (
        <section className="flex flex-col gap-6">
          <Eyebrow tone="muted">01 · POST A JOB</Eyebrow>
          <JobCard
            kind={kind}
            document={document}
            budget={budget}
            demoMode={demoMode}
            running={state.running}
            loadingSample={loadingSample}
            onKind={setKind}
            onDocument={setDocument}
            onBudget={setBudget}
            onDemoMode={setDemoMode}
            onRun={onRun}
          />
        </section>
      ) : (
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-hud-neutral bg-surface px-4 py-2.5 font-mono text-[11px] text-fg-muted">
          <span className="inline-flex items-center gap-2">
            <Eyebrow tone="muted">JOB</Eyebrow>
            <span className="text-fg">
              {state.document?.title ?? localSample(kind).title}
            </span>
          </span>
          <span className="inline-flex items-center gap-3">
            <span className="tabular-nums text-gold">${budget.toFixed(2)} bounty</span>
            {state.finished && (
              <NeonButton variant="ghost" onClick={onReset} className="text-[11px]">
                new job
              </NeonButton>
            )}
          </span>
        </div>
      )}

      {state.error && (
        <div
          className="ax-fade-up flex flex-wrap items-center gap-x-2 rounded-lg border border-danger/40 px-4 py-3 font-mono text-[12.5px] text-danger"
          style={{ background: "rgba(255,59,92,0.06)" }}
        >
          <span className="font-display font-bold uppercase tracking-[0.08em]">
            Error
          </span>
          <span className="text-fg-muted">{state.error}</span>
          {!demoMode && (
            <span className="text-fg-faint">
              Toggle demo mode to play the canned run without a backend.
            </span>
          )}
        </div>
      )}

      {/* ── Live cold-start notice: the Render spin-up reads ~60-90s ──── */}
      {liveStarting && state.running && (
        <div className="ax-fade-up flex flex-wrap items-center gap-x-2.5 gap-y-1 rounded-lg border border-emerald/40 bg-emerald-dim px-4 py-3 font-mono text-[12.5px] text-emerald">
          <LiveDot tone="emerald" size={7} />
          <span className="font-display font-bold uppercase tracking-[0.08em]">
            Spinning up a real Band room…
          </span>
          <span className="text-fg-muted">
            ~60–90s on first call (real Band + agents + x402). Watch the arena —
            it streams as soon as the room is live.
          </span>
        </div>
      )}

      {/* ── Recorded-fallback banner: live was busy/capped/warming up ──── */}
      {fallbackNote && (
        <div className="ax-fade-up flex flex-wrap items-center gap-x-2.5 gap-y-1 rounded-lg border border-gold/40 bg-gold-dim px-4 py-3 font-mono text-[12.5px] text-gold">
          <span className="font-display font-bold uppercase tracking-[0.08em]">
            Recorded run
          </span>
          <span className="text-fg-muted">{fallbackNote}</span>
          <span className="text-fg-faint">
            This is a real Band-room run we recorded earlier — same flow, same
            catch → $0.
          </span>
        </div>
      )}

      {/* ── The stage: the AGENT ARENA ───────────────────────────── */}
      {/* The page is light (.ax-light) and so is the arena now: `.ax-court`
          frames it as a premium light stadium (near-white field, whisper grid,
          hairline border, soft lift) so it sits cohesively on the editorial
          page. Nodes/edges/coins carry their own vivid accents for the signal. */}
      <section id="arena-stage" ref={arenaRef} className="flex flex-col gap-4 scroll-mt-6">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <Eyebrow tone="muted">02 · THE ARENA</Eyebrow>
          {!narratorOn && (
            <NeonButton
              variant="ghost"
              onClick={startCinematic}
              className="text-[11px]"
            >
              ▶ Watch the cinematic
            </NeonButton>
          )}
        </div>
        <div className="ax-court px-3 py-6 sm:px-6 sm:py-8">
          <Arena state={state} demoMode={demoMode} />
        </div>
      </section>

      <footer className="border-t border-hud-neutral pt-7 text-center font-mono text-[11px] uppercase tracking-[0.08em] text-fg-faint">
        bid · hire · work · a calibrated verifier proves the work · USDC settles
        only on proof
      </footer>

      {/* ── Cinematic mode: intro overlay (opening beat) + beat captions ──── */}
      {introUp && (
        <IntroOverlay
          auto={cinematic}
          onLift={() => {
            // Reuse the EXISTING run path — identical to clicking Run.
            window.dispatchEvent(new CustomEvent("ax:run-demo"));
          }}
          onDismissed={() => setIntroUp(false)}
        />
      )}
      {cinematic && (state.running || state.finished) && (
        <BeatCaption state={state} />
      )}
    </main>
  );
}
