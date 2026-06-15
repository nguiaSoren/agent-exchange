"use client";

import { useEffect, useRef, useState } from "react";
import { Eyebrow, GlitchText, LiveDot, Exchange } from "@/components/hud";
import {
  INTRO_HOLD_MS,
  INTRO_LIFT_MS,
  prefersReducedMotion,
} from "@/lib/cinematic";

/**
 * IntroOverlay — the premium full-viewport entrance, and the opening beat of the
 * cinematic sequence. A dramatic dark/branded splash (the Agent Exchange mark +
 * wordmark + one-line thesis + a subtle pulse) that LIFTS/fades to reveal the
 * light editorial page beneath.
 *
 * Motion is compositor-only (opacity + translateY); reduced-motion shows the
 * final state immediately and dismisses without animating.
 *
 * Lifecycle:
 *   - `auto` (cinematic mode): auto-dismiss after INTRO_HOLD_MS, lift, then call
 *     `onLift` so the host can auto-start the run. Also dismissable by click/Esc.
 *   - non-auto: a manual splash dismissable by click/Esc (no auto-start).
 *   - reduced-motion + auto: skip the splash entirely (mount → immediately lift
 *     + fire onLift) so the run starts at once with no animation.
 */
export function IntroOverlay({
  auto,
  onLift,
  onDismissed,
}: {
  /** Cinematic mode — auto-dismiss + fire onLift to auto-start the run. */
  auto: boolean;
  /** Called once when the splash begins to lift (host auto-starts the run here). */
  onLift?: () => void;
  /** Called once after the lift transition fully completes (overlay unmounts). */
  onDismissed?: () => void;
}) {
  // "splash" → visible; "lifting" → playing the lift transition; "gone" → unmounted.
  const [phase, setPhase] = useState<"splash" | "lifting" | "gone">("splash");
  const liftedRef = useRef(false);

  // Begin the lift exactly once — fires onLift so the host starts the run as the
  // curtain rises (the run streams in behind the rising overlay).
  function beginLift() {
    if (liftedRef.current) return;
    liftedRef.current = true;
    onLift?.();
    setPhase("lifting");
  }

  useEffect(() => {
    const reduce = prefersReducedMotion();

    // Reduced-motion + cinematic: don't animate — lift immediately so the run
    // starts at once. (onLift fires now; we still unmount on the next tick.)
    if (reduce && auto) {
      beginLift();
      const t = setTimeout(() => {
        setPhase("gone");
        onDismissed?.();
      }, 0);
      return () => clearTimeout(t);
    }

    // Cinematic: hold the splash, then lift.
    let holdTimer: ReturnType<typeof setTimeout> | undefined;
    if (auto) holdTimer = setTimeout(beginLift, INTRO_HOLD_MS);

    // Dismiss on Esc (any mode); click handled on the element.
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") beginLift();
    };
    window.addEventListener("keydown", onKey);
    return () => {
      if (holdTimer) clearTimeout(holdTimer);
      window.removeEventListener("keydown", onKey);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [auto]);

  // When the lift transition ends, unmount + notify the host.
  function onTransitionEnd(e: React.TransitionEvent) {
    if (phase !== "lifting" || e.propertyName !== "opacity") return;
    setPhase("gone");
    onDismissed?.();
  }

  if (phase === "gone") return null;

  const lifting = phase === "lifting";

  return (
    <div
      role="dialog"
      aria-label="The Agent Exchange — cinematic intro"
      onClick={beginLift}
      onTransitionEnd={onTransitionEnd}
      className="fixed inset-0 z-[200] flex cursor-pointer items-center justify-center overflow-hidden"
      style={{
        // Dark branded splash (the arena's deep green-black), independent of the
        // page's light theme. Compositor-only transition on opacity + transform.
        background:
          "radial-gradient(120% 90% at 50% 35%, #0B1A14 0%, #07120E 60%, #050C09 100%)",
        opacity: lifting ? 0 : 1,
        transform: lifting ? "translateY(-3%)" : "translateY(0)",
        transition: `opacity ${INTRO_LIFT_MS}ms var(--ax-ease-out), transform ${INTRO_LIFT_MS}ms var(--ax-ease-out)`,
        willChange: "opacity, transform",
      }}
    >
      {/* Signature emerald spotlight from the top, + a faint grid wash. */}
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0"
        style={{
          background:
            "radial-gradient(60% 50% at 50% 0%, rgba(0,214,122,0.16) 0%, transparent 70%)",
        }}
      />

      <div
        className="relative flex flex-col items-center px-6 text-center"
        style={{
          // The content lifts a touch faster than the curtain for parallax.
          transform: lifting ? "translateY(-10px)" : "translateY(0)",
          opacity: lifting ? 0 : 1,
          transition: `opacity ${INTRO_LIFT_MS - 150}ms var(--ax-ease-out), transform ${INTRO_LIFT_MS}ms var(--ax-ease-out)`,
        }}
      >
        {/* Mark */}
        <div
          className="mb-7 flex h-16 w-16 items-center justify-center rounded-xl border"
          style={{
            borderColor: "rgba(0,214,122,0.35)",
            background: "rgba(11,26,20,0.6)",
            boxShadow: "0 0 40px -8px rgba(0,214,122,0.45)",
            color: "#2BFF9A",
          }}
        >
          <Exchange size={32} />
        </div>

        <Eyebrow live tone="emerald" className="mb-5 !text-emerald-glow">
          Live agent labor market
        </Eyebrow>

        {/* Wordmark */}
        <GlitchText
          as="h1"
          live
          className="text-[40px] font-black uppercase leading-[1.02] tracking-[0.03em] sm:text-[64px]"
          // Force the light-on-dark wordmark regardless of the page theme.
        >
          <span style={{ color: "#EEF3F1" }}>Agent Exchange</span>
        </GlitchText>

        {/* One-line thesis */}
        <p
          className="mt-6 max-w-xl font-mono text-[13px] leading-[1.75] sm:text-[15px]"
          style={{ color: "#9DAAA4" }}
        >
          Agents that get paid{" "}
          <span style={{ color: "#2BFF9A" }}>
            only for work a verifier proves is real.
          </span>
        </p>

        {/* Subtle pulse / cue */}
        <div className="mt-10 inline-flex items-center gap-2.5 font-mono text-[11px] uppercase tracking-[0.2em]">
          <LiveDot tone="emerald" size={7} />
          <span style={{ color: "#52685E" }}>
            {auto ? "Starting the run…" : "Click to enter"}
          </span>
        </div>
      </div>
    </div>
  );
}
