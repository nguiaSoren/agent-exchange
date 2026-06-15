"use client";

import { useCallback, useEffect, useReducer, useRef, useState } from "react";
import dynamic from "next/dynamic";
import type { ExchangeEvent, JobKind, RunRequest } from "@/lib/events";
import { applyEvent, initialState, type RunState } from "@/lib/runState";
import { runJob, fetchSample, API_BASE } from "@/lib/stream";
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

  // The launch console collapses once a run is active so the arena owns the
  // stage; it returns on reset (idle) so a new job can be posted.
  const narratorOn = state.running || state.finished;
  const consoleOpen = !narratorOn;

  const onRun = useCallback(async () => {
    abortRef.current?.();
    const myRun = ++runIdRef.current;
    // C3: show "Assembling" micro-state immediately — before any event lands
    setStarting(true);
    dispatch({ kind: "start" });

    // The console collapses on this render and the arena takes the stage —
    // scroll it FULLY into view (bottom corners + legend) after the relayout
    // paints. Two rAFs so the collapsed layout has settled first.
    requestAnimationFrame(() =>
      requestAnimationFrame(() => scrollIntoFullView(arenaRef.current)),
    );

    const req: RunRequest = {
      kind,
      document,
      budget_usd: budget,
      mode: demoMode ? "sim" : "live",
    };

    try {
      if (demoMode) {
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
        for await (const ev of handle.events) {
          if (runIdRef.current !== myRun) return;
          setStarting(false);
          dispatch({ kind: "event", ev });
        }
      }
    } catch (err) {
      if (runIdRef.current !== myRun) return;
      setStarting(false);
      dispatch({
        kind: "event",
        ev: {
          type: "error",
          data: { message: err instanceof Error ? err.message : String(err) },
        },
      });
    }
  }, [kind, document, budget, demoMode]);

  // Landing CTAs ("Watch it run" / "Run the live demo") fire `ax:run-demo` to
  // start the demo exactly like clicking Run — same code path ⇒ the demo plays
  // AND the arena scrolls to the identical position.
  useEffect(() => {
    const handler = () => onRun();
    window.addEventListener("ax:run-demo", handler);
    return () => window.removeEventListener("ax:run-demo", handler);
  }, [onRun]);

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
