"use client";

import type { RunState } from "@/lib/runState";
import { LiveDot } from "./LiveDot";

/** Maps each pipeline stage name to its one-line story beat. */
const STAGE_GUIDE: Record<string, string> = {
  Post: "Posting the job — a document to audit and a USDC bounty.",
  Discover: "Discovering agents across owners…",
  Bid: "Agents are bidding — ranked by reputation.",
  Hire: "Hiring the team under budget.",
  Work: "The team is auditing the document in a shared room…",
  Verify: "The verifier is checking every claim against the document.",
  Settle: "Settling — paying only for verified work; fabrications get $0.",
  Done: "Done — real work paid, fabrications withheld.",
};

/** The current step: active stage if any, else the last non-pending one. */
export function currentStep(
  stages: RunState["stages"]
): { name: string; index: number } | null {
  if (stages.length === 0) return null;
  const active = stages.findIndex((s) => s.status === "active");
  if (active !== -1) return { name: stages[active].name, index: active };
  let lastTouched = -1;
  for (let i = 0; i < stages.length; i++) {
    if (stages[i].status !== "pending") lastTouched = i;
  }
  if (lastTouched === -1) return null;
  return { name: stages[lastTouched].name, index: lastTouched };
}

export interface NarratorProps {
  stages: RunState["stages"];
  /** True while the run is actively streaming events. */
  running: boolean;
  /** True once the run has completed. */
  finished: boolean;
  /**
   * When true (Dashboard only), the run has been triggered but no events have
   * arrived yet. Shows an "Assembling" micro-state for <100 ms feedback.
   */
  starting?: boolean;
  /**
   * Override the idle placeholder message.
   * Defaults to "Press Run to start the live audit."
   */
  idlePlaceholder?: string;
  /**
   * When true, the narrator wrapper does NOT dim in the idle/placeholder state.
   * ReplayDashboard passes `loaded` here so the bar stays full-opacity once a
   * file is loaded even before play begins.
   */
  alwaysOn?: boolean;
}

/**
 * Narrator — the one-line stage caption bar driven off `stages`.
 *
 * Renders three possible states:
 *   1. Active / finished — "NOW · <line>" or "Result · <line>" with step counter.
 *   2. Starting micro-state — "Assembling the roster…" with a gold dot.
 *   3. Idle placeholder — dashed border, muted dot, custom idle text.
 */
export function Narrator({
  stages,
  running,
  finished,
  starting = false,
  idlePlaceholder = "Press Run to start the live audit.",
  alwaysOn = false,
}: NarratorProps) {
  const step = currentStep(stages);
  const line = step ? (STAGE_GUIDE[step.name] ?? null) : null;
  const totalStages = stages.length;
  const narratorOn = running || finished;
  const wrapperOpacity = narratorOn || alwaysOn ? "" : "opacity-70";

  return (
    <div aria-live="polite" className={`-mt-2 ${wrapperOpacity}`}>
      {starting && !narratorOn ? (
        /* C3: Assembling micro-state — immediate feedback on Run press */
        <div className="ax-fade-up flex items-center gap-2 rounded-lg border border-hud-neutral bg-surface px-4 py-3 font-mono text-[12.5px]">
          <LiveDot tone="gold" size={7} />
          <span className="text-fg-muted">Assembling the roster…</span>
        </div>
      ) : narratorOn && line ? (
        <div className="ax-fade-up flex flex-wrap items-center gap-x-3 gap-y-2 rounded-lg border border-hud-neutral bg-surface px-4 py-3 font-mono text-[12.5px]">
          <span className="inline-flex items-center gap-2 shrink-0">
            <LiveDot tone={finished ? "emerald" : "gold"} size={7} />
            <span className="font-semibold uppercase tracking-[0.18em] text-fg-muted">
              {finished ? "Result" : "Now"}
            </span>
          </span>
          <span className="text-fg">{line}</span>
          {step && (
            <span className="ml-auto shrink-0 tabular-nums text-fg-faint">
              {step.name} · {step.index + 1}/{totalStages}
            </span>
          )}
        </div>
      ) : (
        <div className="flex items-center gap-2 rounded-lg border border-dashed border-hud-neutral bg-surface px-4 py-3 font-mono text-[12px] text-fg-faint">
          <LiveDot tone="muted" size={6} pulse={false} />
          {idlePlaceholder}
        </div>
      )}
    </div>
  );
}
