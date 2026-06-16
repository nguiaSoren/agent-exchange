/**
 * Cinematic auto-play demo — shared constants + helpers.
 *
 * The cinematic mode is a one-trigger, on-rails performance of the whole arena
 * run, tuned for screen-recording a ~3-minute demo. It does NOT fork the run
 * logic: it reuses the EXISTING demo path (the same `onRun` the Run button and
 * the landing CTAs use). This module only holds the trigger detection, the
 * pacing constants, and the per-stage beat-caption copy.
 *
 * Tempo (LOCKED — drives the recording):
 *   - Intro overlay holds for INTRO_HOLD_MS, then lifts (≈700ms compositor
 *     transition) and the run auto-starts on its native ~18.2s mockRun tempo
 *     (fixed delays in lib/mockRun.ts — NOT sped up; lively but legible).
 *   - The arena's own GATE auto-scroll fires when `state.done` lands.
 *   - We then LINGER on the GATE for GATE_LINGER_MS, smooth-scroll to
 *     #research, and LINGER there for RESEARCH_LINGER_MS.
 * Total ≈ 2 + 0.7 + 18.2 + 2.5 + (~1 scroll) + 4 ≈ 28s of on-rails playback,
 * comfortably inside a 3-minute recording window with room to narrate.
 */

/** Hold the intro splash before it lifts (ms). */
export const INTRO_HOLD_MS = 2000;
/** Intro lift/fade transition duration (ms) — compositor-only opacity+transform. */
export const INTRO_LIFT_MS = 700;
/** Linger on the GATE summary after the run finishes, before scrolling on (ms). */
export const GATE_LINGER_MS = 2500;
/** Linger on the #research finale after scrolling to it (ms). */
export const RESEARCH_LINGER_MS = 4000;
/**
 * Delay multiplier for the demo run when played in cinematic mode — stretches
 * mockRun's native ~18s tempo so each stage (and its beat caption) lingers long
 * enough to read comfortably. ~2× → ~36s of legible, on-rails playback. Normal
 * click-to-run is unaffected (scale 1).
 */
export const CINEMATIC_DELAY_SCALE = 2.0;

/** Was the page opened in cinematic auto-play mode (`?demo=cinematic`)? */
export function isCinematicParam(): boolean {
  if (typeof window === "undefined") return false;
  const v = new URLSearchParams(window.location.search).get("demo");
  return v === "cinematic";
}

/** Does the viewer prefer reduced motion? (cinematic skips straight to the run.) */
export function prefersReducedMotion(): boolean {
  if (typeof window === "undefined") return false;
  return window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;
}

/**
 * One beat caption per pipeline stage — short, punchy lower-thirds shown over
 * the dark arena court during the cinematic run. Keyed by the stage `name`
 * emitted by mockRun (Post → Discover → Bid → Hire → Work → Verify → Settle →
 * Done). The captions name what is happening for the camera; they intentionally
 * read more dramatically than the in-product Narrator copy.
 */
export interface Beat {
  /** Tiny eyebrow / kicker above the headline. */
  kicker: string;
  /** The punchy headline line. */
  line: string;
  /** Accent tone for the dot + kicker. (`cyan` = the human-in-the-loop beat.) */
  tone: "emerald" | "gold" | "red" | "cyan";
}

export const BEATS: Record<string, Beat> = {
  Post: {
    kicker: "The job",
    line: "A contract goes up for audit — with a USDC bounty attached.",
    tone: "gold",
  },
  Discover: {
    kicker: "Discovery",
    line: "Agents found · CrewAI, LangGraph + native — 2 owners, incl. a cross-owner specialist.",
    tone: "emerald",
  },
  Bid: {
    kicker: "The market",
    line: "Agents bid — priced and ranked by reputation.",
    tone: "gold",
  },
  Hire: {
    kicker: "Cross-org recruit",
    line: "Hired an agent you don't own — across orgs, via Band.",
    tone: "gold",
  },
  Work: {
    kicker: "Collaboration",
    line: "The team audits the contract together in a shared room.",
    tone: "gold",
  },
  Verify: {
    kicker: "The verifier",
    line: "Every claim is checked against the contract — one is fabricated.",
    tone: "emerald",
  },
  // The human-in-the-loop beat — NOT a pipeline stage. BeatCaption swaps this in
  // (overriding the Verify caption) while a sub-threshold claim is escalated and
  // a human is reviewing it, then lingers on the approval before Settle.
  Human: {
    kicker: "Human in the loop",
    line: "Too unsure to pass alone — a human is pulled in, reviews, and approves the honest work.",
    tone: "cyan",
  },
  Settle: {
    kicker: "Settlement",
    line: "Fabrication caught → payment withheld. Honest work settles in USDC.",
    tone: "red",
  },
  Done: {
    kicker: "Proof",
    line: "Real work paid · fabricated work earns exactly $0.",
    tone: "emerald",
  },
};
