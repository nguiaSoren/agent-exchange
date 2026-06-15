"use client";

import { useEffect, useRef, useState } from "react";
import type { RunState } from "@/lib/runState";
import { currentStep } from "@/components/hud";
import { LiveDot } from "@/components/hud";
import { BEATS } from "@/lib/cinematic";

/**
 * BeatCaption — the cinematic lower-third. A tasteful, fixed-position corner
 * caption that names the current beat of the run ("Agents found…", "Fabrication
 * caught → payment withheld", …), synced to the ACTIVE pipeline stage.
 *
 * It reads the stage off `state.stages` via the shared `currentStep` helper —
 * it does NOT drive the run; it narrates it. One caption per stage; it fades in
 * and out (compositor-only opacity + translateY) on each stage change.
 *
 * Light text over the dark arena court (a dark glassy plate), legible against
 * the light page behind. Only mounted while cinematic mode is active.
 */
export function BeatCaption({ state }: { state: RunState }) {
  const step = currentStep(state.stages);
  const name = step?.name ?? null;
  const beat = name ? BEATS[name] : null;

  // Re-trigger the fade on each beat change by keying a transient "shown" flag.
  const [shown, setShown] = useState(false);
  const prevName = useRef<string | null>(null);

  useEffect(() => {
    if (!beat) {
      setShown(false);
      return;
    }
    if (name !== prevName.current) {
      prevName.current = name;
      // Out → in: brief flicker so consecutive beats visibly hand off.
      setShown(false);
      const t = setTimeout(() => setShown(true), 40);
      return () => clearTimeout(t);
    }
    setShown(true);
  }, [name, beat]);

  if (!beat) return null;

  const accent =
    beat.tone === "emerald"
      ? "#2BFF9A"
      : beat.tone === "red"
        ? "#FF3B5C"
        : "#FFC233";

  return (
    <div
      aria-hidden
      className="pointer-events-none fixed inset-x-0 bottom-6 z-[150] flex justify-center px-4 sm:bottom-10"
    >
      <div
        className="flex max-w-[640px] items-center gap-3.5 rounded-lg border px-5 py-3.5"
        style={{
          borderColor: "rgba(0,214,122,0.22)",
          background: "rgba(7,18,14,0.92)",
          boxShadow:
            "0 18px 40px -16px rgba(0,0,0,0.7), 0 0 0 1px rgba(255,255,255,0.04)",
          opacity: shown ? 1 : 0,
          transform: shown ? "translateY(0)" : "translateY(10px)",
          transition:
            "opacity 320ms var(--ax-ease-out), transform 320ms var(--ax-ease-out)",
          willChange: "opacity, transform",
        }}
      >
        <LiveDot tone={beat.tone} size={8} />
        <div className="flex flex-col text-left">
          <span
            className="font-mono text-[9.5px] font-medium uppercase tracking-[0.22em]"
            style={{ color: accent }}
          >
            {beat.kicker}
          </span>
          <span
            className="mt-0.5 font-mono text-[13px] leading-snug sm:text-[14px]"
            style={{ color: "#EEF3F1" }}
          >
            {beat.line}
          </span>
        </div>
      </div>
    </div>
  );
}
