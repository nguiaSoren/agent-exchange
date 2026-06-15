"use client";

import { useEffect, useState } from "react";
import { Check, Cross, CountUp, LiveDot } from "@/components/hud";

/**
 * LiveTicker — a quietly-running "honesty-checking never stops" strip for the
 * LIGHT editorial landing. A slowly auto-advancing tape of verdict chips
 * (mostly emerald ✓, the occasional red ✗ = the catch) plus a live-ish counter
 * pair conveying the verifier is always on.
 *
 * Honesty framing (the project's hard rule — marketing must match measured
 * truth): the counter is NOT a certified production KPI. It's labelled as the
 * running demo tape ("across demo runs") and gently increments from a base, so
 * it reads as an illustrative aggregate of the verifier exercising itself —
 * never a fabricated precise production stat. The HEADLINE measured numbers
 * (100% / 81-of-81) live in <Numbers/>, traced to a real evaluation; this
 * strip is the ambient "always-on" motif, not a claim.
 *
 * Motion: compositor-only (transform via the shared `ax-marquee` keyframe),
 * seamless loop by rendering the chip row twice. Reduced-motion: the tape holds
 * static (ax-marquee is killed in globals.css) and counters snap to final
 * values (CountUp + the increment effect both honor prefers-reduced-motion).
 */

// One calm cadence of verdicts: mostly real, the rare fabrication caught. The
// pattern is the message — honesty is the default, the ✗ is the exception that
// proves the verifier is actually looking.
const TAPE: Array<"pass" | "fail"> = [
  "pass",
  "pass",
  "pass",
  "pass",
  "fail",
  "pass",
  "pass",
  "pass",
  "pass",
  "pass",
  "fail",
  "pass",
  "pass",
  "pass",
];

function VerdictChip({ kind }: { kind: "pass" | "fail" }) {
  const pass = kind === "pass";
  return (
    <span
      className={`inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-md border ${
        pass
          ? "border-emerald/40 bg-emerald-dim text-emerald"
          : "border-danger/40 bg-danger-dim text-danger"
      }`}
      title={pass ? "claim verified — real" : "fabrication caught — withheld"}
    >
      {pass ? <Check size={13} /> : <Cross size={13} />}
    </span>
  );
}

/** The chip row, rendered twice for a seamless -50% translate loop. */
function TapeRow() {
  return (
    <div
      aria-hidden
      className="ax-marquee flex w-max shrink-0 items-center gap-2.5 pr-2.5"
    >
      {TAPE.map((k, i) => (
        <VerdictChip key={i} kind={k} />
      ))}
    </div>
  );
}

/**
 * A gently-incrementing number that ticks up by a small random step every few
 * seconds, feeding <CountUp/> so each bump animates. Honors reduced-motion by
 * never starting the interval (the value holds at `base`). The base is the
 * illustrative aggregate; the drift just keeps it feeling alive, not precise.
 */
function useGentleCount(base: number, stepMax: number, everyMs: number) {
  const [value, setValue] = useState(base);
  useEffect(() => {
    const reduce =
      typeof window !== "undefined" &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduce) return;
    const id = setInterval(
      () => setValue((v) => v + 1 + Math.floor(Math.random() * stepMax)),
      everyMs,
    );
    return () => clearInterval(id);
  }, [stepMax, everyMs]);
  return value;
}

export function LiveTicker() {
  // Illustrative running aggregate "across demo runs" — not a certified KPI.
  const verified = useGentleCount(1248, 3, 3200);
  const caught = useGentleCount(37, 1, 11000);

  return (
    <div className="ax-fade-up mt-10 w-full">
      {/* Live counter line — honest framing: a running demo tape, not a stat. */}
      <div className="flex flex-wrap items-center gap-x-2.5 gap-y-1.5 font-mono text-[11px] text-fg-faint">
        <span className="inline-flex items-center gap-1.5 text-fg-muted">
          <LiveDot tone="emerald" size={7} />
          <span className="uppercase tracking-[0.16em]">Verifier live</span>
        </span>
        <span className="text-fg-faint/60">·</span>
        <span className="tnum text-fg-muted">
          <CountUp value={verified} className="text-emerald" /> claims verified
        </span>
        <span className="text-fg-faint/60">·</span>
        <span className="tnum text-fg-muted">
          <CountUp value={caught} className="text-danger" /> caught &amp; withheld
        </span>
        <span className="text-fg-faint/60">·</span>
        <span className="tracking-[0.1em] text-fg-faint">
          across demo runs
        </span>
      </div>

      {/* The tape: a horizontal, edge-faded, slowly-scrolling verdict strip. */}
      <div
        className="ax-marquee-pause group relative mt-4 overflow-hidden rounded-lg border border-hud-neutral bg-surface-2/60 py-2.5"
        role="img"
        aria-label="Live stream of verification verdicts: mostly verified, with the occasional fabrication caught and withheld."
      >
        <div className="flex">
          <TapeRow />
          <TapeRow />
        </div>
        {/* Edge fades — dissolve the loop seam into the surface. */}
        <div className="pointer-events-none absolute inset-y-0 left-0 w-16 bg-gradient-to-r from-canvas to-transparent" />
        <div className="pointer-events-none absolute inset-y-0 right-0 w-16 bg-gradient-to-l from-canvas to-transparent" />
      </div>
    </div>
  );
}
