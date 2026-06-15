"use client";

/**
 * useReplay — playback hook for agent-exchange replay files.
 *
 * Folds replay events through the same applyEvent reducer the live dashboard
 * uses, so <Arena state={ctl.state} /> renders identically to a live run.
 *
 * Implements ReplayController exactly as specified in REPLAY_ROUTE_SPEC.md.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { applyEvent, initialState } from "@/lib/runState";
import type { RunState } from "@/lib/runState";
import type { DoneEvent, ExchangeEvent } from "@/lib/events";

// ---------------------------------------------------------------------------
// Public types
// ---------------------------------------------------------------------------

export interface ReplayMeta {
  schema: string;
  job_id: string;
  kind: string;
  mode: string;
  title: string;
  budget_usd: number;
  recorded_at: string;
  seed: number;
  totals: DoneEvent | null;
  tx_links: { worker: string; tx_hash: string; explorer: string }[];
}

/** A single event as it appears in the replay file. */
interface ReplayEvent {
  seq: number;
  t_offset_ms: number;
  type: string;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  data: any; // cast to ExchangeEvent below — unavoidable union discriminant gap
}

/** Internal loaded replay (meta stripped of events). */
interface LoadedReplay {
  meta: ReplayMeta;
  events: ReplayEvent[];
}

export interface ReplayController {
  status: "empty" | "loading" | "loaded" | "error";
  error: string | null;
  meta: ReplayMeta | null;
  state: RunState;          // events[0..cursor] folded through applyEvent
  cursor: number;           // -1 .. total-1  (-1 = nothing applied yet)
  total: number;            // events.length
  currentType: string | null; // events[cursor]?.type ?? null
  playing: boolean;
  speed: number;            // one of 0.5 | 1 | 2 | 4

  loadFromUrl: (url: string) => Promise<void>;
  loadFromFile: (file: File) => Promise<void>;
  play: () => void;
  pause: () => void;
  toggle: () => void;
  seek: (i: number) => void;     // clamp to [-1, total-1]
  stepFwd: () => void;
  stepBack: () => void;
  cycleSpeed: () => void;        // 0.5 → 1 → 2 → 4 → 0.5
  jumpToCatch: () => void;       // first index where type==='finding' && data.verdict==='unsupported'
  restart: () => void;           // cursor = -1, paused
}

// ---------------------------------------------------------------------------
// Beat timing (ms at speed=1) keyed to event type
// ---------------------------------------------------------------------------

const SPEED_STEPS: number[] = [0.5, 1, 2, 4];

function beatMs(eventType: string | undefined): number {
  switch (eventType) {
    case "stage":
      return 700;
    case "settle":
      return 600;
    case "bid":
    case "finding":
    case "room_message":
      return 350;
    default:
      return 450;
  }
}

// ---------------------------------------------------------------------------
// Schema validation
// ---------------------------------------------------------------------------

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function parseReplay(raw: any): LoadedReplay {
  if (
    typeof raw !== "object" ||
    raw === null ||
    typeof raw.schema !== "string" ||
    !raw.schema.startsWith("agent-exchange.replay/")
  ) {
    throw new Error(
      `Invalid replay schema: expected "agent-exchange.replay/…", got ${JSON.stringify(raw?.schema)}`
    );
  }

  const events: ReplayEvent[] = Array.isArray(raw.events) ? raw.events : [];

  // Build meta: everything except events[]
  const { events: _drop, ...rest } = raw as { events: unknown } & Record<string, unknown>;
  void _drop;

  const meta: ReplayMeta = {
    schema: String(rest.schema ?? ""),
    job_id: String(rest.job_id ?? ""),
    kind: String(rest.kind ?? ""),
    mode: String(rest.mode ?? ""),
    title: String(rest.title ?? ""),
    budget_usd: typeof rest.budget_usd === "number" ? rest.budget_usd : 0,
    recorded_at: String(rest.recorded_at ?? ""),
    seed: typeof rest.seed === "number" ? rest.seed : 0,
    totals:
      rest.totals != null && typeof rest.totals === "object"
        ? (rest.totals as DoneEvent)
        : null,
    tx_links: Array.isArray(rest.tx_links)
      ? (rest.tx_links as { worker: string; tx_hash: string; explorer: string }[])
      : [],
  };

  return { meta, events };
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

export function useReplay(opts?: {
  autoloadUrl?: string;
  /** Initial playback speed (default 1). The hero shots run fast (4×) so the
   *  catch → $0 payoff lands quickly; the catch-beat hold is real-time regardless. */
  initialSpeed?: number;
}): ReplayController {
  const [status, setStatus] = useState<ReplayController["status"]>("empty");
  const [error, setError] = useState<string | null>(null);
  const [replay, setReplay] = useState<LoadedReplay | null>(null);
  const [cursor, setCursor] = useState<number>(-1);
  const [playing, setPlaying] = useState<boolean>(false);
  const [speed, setSpeed] = useState<number>(opts?.initialSpeed ?? 1);

  // Timer ref — cleared whenever playback stops or cursor moves manually
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Guard for strict-mode double-mount on autoload
  const autoloadFiredRef = useRef<boolean>(false);

  // ---------------------------------------------------------------------------
  // Pure derived values (memoised)
  // ---------------------------------------------------------------------------

  const events = replay?.events ?? [];
  const total = events.length;

  /** Pure fold: events[0..cursor] → RunState.
   *
   * Seed with `running: true` (mirroring the live dashboard's "start" dispatch,
   * which sets `fresh.running = true` before streaming). The Arena gates its
   * non-idle channel — edge glow/activation, brightness, pings — on
   * `state.running`; without this seed a replay renders dim/idle and the edges
   * never light up. The terminal `done` event flips running→false, finished→true. */
  const state = useMemo<RunState>(() => {
    if (cursor < 0 || events.length === 0) return initialState();
    const seed = initialState();
    seed.running = true;
    return events
      .slice(0, cursor + 1)
      .reduce(
        (s, e) => applyEvent(s, { type: e.type, data: e.data } as ExchangeEvent),
        seed
      );
  }, [replay, cursor]); // eslint-disable-line react-hooks/exhaustive-deps
  // replay change resets cursor anyway; listing events as dep would bust memo
  // every render since the array reference lives inside replay.

  const currentType: string | null = events[cursor]?.type ?? null;

  // ---------------------------------------------------------------------------
  // Helpers
  // ---------------------------------------------------------------------------

  function clearTimer() {
    if (timerRef.current !== null) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
  }

  // ---------------------------------------------------------------------------
  // Load helpers
  // ---------------------------------------------------------------------------

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  function applyLoaded(raw: any) {
    try {
      const loaded = parseReplay(raw);
      setReplay(loaded);
      setCursor(-1);
      setPlaying(false);
      setError(null);
      setStatus("loaded");
    } catch (err) {
      setStatus("error");
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  const loadFromUrl = useCallback(async (url: string): Promise<void> => {
    clearTimer();
    setStatus("loading");
    setError(null);
    try {
      const res = await fetch(url);
      if (!res.ok) {
        throw new Error(`HTTP ${res.status} fetching ${url}`);
      }
      const raw: unknown = await res.json();
      applyLoaded(raw);
    } catch (err) {
      setStatus("error");
      setError(err instanceof Error ? err.message : String(err));
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const loadFromFile = useCallback(async (file: File): Promise<void> => {
    clearTimer();
    setStatus("loading");
    setError(null);
    try {
      const text = await file.text();
      const raw: unknown = JSON.parse(text);
      applyLoaded(raw);
    } catch (err) {
      setStatus("error");
      setError(err instanceof Error ? err.message : String(err));
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // ---------------------------------------------------------------------------
  // Autoload (once on mount; strict-mode safe)
  // ---------------------------------------------------------------------------

  useEffect(() => {
    if (!opts?.autoloadUrl) return;
    if (autoloadFiredRef.current) return;
    autoloadFiredRef.current = true;
    void loadFromUrl(opts.autoloadUrl);
  }, [opts?.autoloadUrl, loadFromUrl]);

  // ---------------------------------------------------------------------------
  // Playback engine
  // ---------------------------------------------------------------------------

  // We store speed in a ref so the setTimeout closure always reads the latest
  // value without needing to restart the chain.
  const speedRef = useRef<number>(speed);
  useEffect(() => { speedRef.current = speed; }, [speed]);

  // We store playing in a ref for the same reason.
  const playingRef = useRef<boolean>(playing);
  useEffect(() => { playingRef.current = playing; }, [playing]);

  // Cursor ref so setTimeout closure can read latest without stale closure.
  const cursorRef = useRef<number>(cursor);
  useEffect(() => { cursorRef.current = cursor; }, [cursor]);

  const totalRef = useRef<number>(total);
  useEffect(() => { totalRef.current = total; }, [total]);

  // The recursive step function lives in a ref so it can call itself.
  const stepFn = useRef<() => void>(() => undefined);

  stepFn.current = () => {
    if (!playingRef.current) return;

    const cur = cursorRef.current;
    const tot = totalRef.current;

    if (tot === 0) {
      setPlaying(false);
      return;
    }

    const next = cur + 1;

    if (next >= tot) {
      // Reached the end — stop.
      setPlaying(false);
      return;
    }

    // Advance cursor.
    cursorRef.current = next;
    setCursor(next);

    // Schedule the step after this new cursor's event.
    // The delay is keyed to the type of the CURRENT event we just landed on,
    // which is what the user sees — effectively "how long to show this frame".
    // The spec says "NEXT event's type"; the next event after position `next` is
    // at `next+1`. We use that to set the delay before advancing again.
    const lookaheadType: string | undefined = events[next + 1]?.type;
    const delay = beatMs(lookaheadType) / speedRef.current;

    timerRef.current = setTimeout(() => stepFn.current(), delay);
  };

  // We need `events` inside the closure above. Keep it in a ref.
  const eventsRef = useRef<ReplayEvent[]>(events);
  useEffect(() => { eventsRef.current = events; }, [events]);

  // Override stepFn to use eventsRef so it doesn't stale-close over events.
  stepFn.current = () => {
    if (!playingRef.current) return;

    const cur = cursorRef.current;
    const tot = totalRef.current;
    const evs = eventsRef.current;

    if (tot === 0) {
      setPlaying(false);
      return;
    }

    const next = cur + 1;

    if (next >= tot) {
      setPlaying(false);
      return;
    }

    cursorRef.current = next;
    setCursor(next);

    const lookaheadType: string | undefined = evs[next + 1]?.type;
    const delay = beatMs(lookaheadType) / speedRef.current;

    timerRef.current = setTimeout(() => stepFn.current(), delay);
  };

  // Cleanup on unmount.
  useEffect(() => {
    return () => clearTimer();
  }, []);

  // ---------------------------------------------------------------------------
  // Public controls
  // ---------------------------------------------------------------------------

  const pause = useCallback(() => {
    clearTimer();
    setPlaying(false);
  }, []);

  const play = useCallback(() => {
    const tot = totalRef.current;
    if (tot === 0) return;

    // If at end, restart from -1 first.
    if (cursorRef.current >= tot - 1) {
      cursorRef.current = -1;
      setCursor(-1);
    }

    // Kick off — set playing=true, then schedule the first step.
    playingRef.current = true;
    setPlaying(true);

    const lookaheadType: string | undefined = eventsRef.current[cursorRef.current + 1]?.type;
    const delay = beatMs(lookaheadType) / speedRef.current;

    timerRef.current = setTimeout(() => stepFn.current(), delay);
  }, []);

  const toggle = useCallback(() => {
    if (playingRef.current) {
      pause();
    } else {
      play();
    }
  }, [pause, play]);

  const seek = useCallback((i: number) => {
    clearTimer();
    setPlaying(false);
    playingRef.current = false;
    const clamped = Math.max(-1, Math.min(i, totalRef.current - 1));
    cursorRef.current = clamped;
    setCursor(clamped);
  }, []);

  const stepFwd = useCallback(() => {
    clearTimer();
    setPlaying(false);
    playingRef.current = false;
    const next = Math.min(cursorRef.current + 1, totalRef.current - 1);
    cursorRef.current = next;
    setCursor(next);
  }, []);

  const stepBack = useCallback(() => {
    clearTimer();
    setPlaying(false);
    playingRef.current = false;
    const prev = Math.max(cursorRef.current - 1, -1);
    cursorRef.current = prev;
    setCursor(prev);
  }, []);

  const cycleSpeed = useCallback(() => {
    setSpeed((s) => {
      const idx = SPEED_STEPS.indexOf(s);
      return SPEED_STEPS[(idx + 1) % SPEED_STEPS.length] ?? 1;
    });
  }, []);

  const jumpToCatch = useCallback(() => {
    const evs = eventsRef.current;
    const idx = evs.findIndex(
      (e) => e.type === "finding" && e.data?.verdict === "unsupported"
    );
    if (idx === -1) return; // no unsupported finding — no-op
    clearTimer();
    setPlaying(false);
    playingRef.current = false;
    cursorRef.current = idx;
    setCursor(idx);
  }, []);

  const restart = useCallback(() => {
    clearTimer();
    setPlaying(false);
    playingRef.current = false;
    cursorRef.current = -1;
    setCursor(-1);
  }, []);

  // ---------------------------------------------------------------------------
  // Return
  // ---------------------------------------------------------------------------

  return {
    status,
    error,
    meta: replay?.meta ?? null,
    state,
    cursor,
    total,
    currentType,
    playing,
    speed,

    loadFromUrl,
    loadFromFile,
    play,
    pause,
    toggle,
    seek,
    stepFwd,
    stepBack,
    cycleSpeed,
    jumpToCatch,
    restart,
  };
}
