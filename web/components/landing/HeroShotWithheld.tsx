"use client";

import { useCallback, useEffect, useRef } from "react";
import dynamic from "next/dynamic";

import { useReplay } from "@/lib/useReplay";
import { NeonButton } from "@/components/hud";
import { HeroShell, type HeroMetric } from "./HeroShell";

/**
 * HERO SHOT 01 — "lie detected → payment withheld."
 *
 * Not a mockup: this reuses the REAL arena, driven by the REAL replay reducer,
 * playing the canned `sim-contract-audit-seeded-liar` run. That run withholds
 * everything — the gate fails, $0 settles, $0.115 is withheld — and the
 * fabricator's node lands a red ✗ and gets NO coin. The "coin does not move on
 * red ✗" payoff is literally what the arena renders on the done frame.
 *
 * It auto-plays when scrolled into view (IntersectionObserver), holds on the
 * $0 done frame, and honours prefers-reduced-motion by jumping straight to the
 * payoff instead of animating.
 */

// Arena is heavy and pulls @lobehub/icons (not SSR-safe) — load it client-only,
// mirroring Dashboard.tsx / ReplayDashboard.tsx exactly, placeholder included.
const Arena = dynamic(() => import("@/components/arena").then((m) => m.Arena), {
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

const REPLAY_URL = "/replays/sim-contract-audit-seeded-liar.replay.json";

const METRICS: HeroMetric[] = [
  { value: "$0", label: "settled on fabrication", tone: "danger" },
  { value: "1", label: "lie caught", tone: "emerald" },
  { value: "100%", label: "catch rate", tone: "emerald" },
];

function prefersReducedMotion(): boolean {
  return (
    typeof window !== "undefined" &&
    !!window.matchMedia &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches
  );
}

export function HeroShotWithheld() {
  const ctl = useReplay({ autoloadUrl: REPLAY_URL, initialSpeed: 4 });

  // The section we watch for scroll-into-view.
  const sectionRef = useRef<HTMLDivElement>(null);

  // Has the current on-screen entry already triggered playback? Reset when the
  // section leaves the viewport, so re-entering replays the moment once more.
  const playedThisEntryRef = useRef(false);

  // Keep the latest controller in a ref so the IntersectionObserver effect can
  // stay mounted once (empty deps) without stale-closing over ctl methods.
  const ctlRef = useRef(ctl);
  ctlRef.current = ctl;

  // Drives the moment: animate the lifecycle, OR (reduced motion) jump straight
  // to the catch beat and then the $0 done frame so the payoff still shows.
  const triggerMoment = useCallback(() => {
    const c = ctlRef.current;
    if (c.total === 0) return; // replay not loaded yet — wait for next IO tick
    if (prefersReducedMotion()) {
      c.jumpToCatch();
      c.seek(c.total - 1);
      return;
    }
    c.restart();
    c.play();
  }, []);

  useEffect(() => {
    const el = sectionRef.current;
    if (!el || typeof IntersectionObserver === "undefined") {
      // No IO support: show the payoff statically rather than an idle ring.
      triggerMoment();
      return;
    }

    const io = new IntersectionObserver(
      (entries) => {
        const entry = entries[0];
        if (!entry) return;
        if (entry.isIntersecting && entry.intersectionRatio >= 0.4) {
          if (!playedThisEntryRef.current) {
            playedThisEntryRef.current = true;
            triggerMoment();
          }
        } else {
          // Left view: pause for perf, and arm the next entry to replay.
          playedThisEntryRef.current = false;
          ctlRef.current.pause();
        }
      },
      { threshold: [0, 0.4, 0.75] }
    );

    io.observe(el);
    return () => io.disconnect();
  }, [triggerMoment]);

  const onReplay = useCallback(() => {
    const c = ctlRef.current;
    playedThisEntryRef.current = true; // we're handling the replay explicitly
    if (prefersReducedMotion()) {
      c.jumpToCatch();
      c.seek(c.total - 1);
      return;
    }
    c.restart();
    c.play();
  }, []);

  const visual = (
    <div ref={sectionRef} className="flex flex-col items-center gap-3">
      {/* Constrain the column so the responsive arena reads tight & cinematic.
          (Arena caps itself ~720 via ResizeObserver; ~520 keeps neon dense.) */}
      <div className="w-full max-w-[520px]">
        <div className="ax-court px-3 py-5 sm:px-5 sm:py-6">
          <Arena state={ctl.state} idleHint={null} />
        </div>
      </div>

      <div className="flex w-full max-w-[520px] items-center justify-between px-1">
        <span className="font-mono text-[10px] uppercase tracking-[0.16em] text-fg-faint">
          gate failed · $0 settled · $0.115 withheld
        </span>
        <NeonButton
          variant="ghost"
          onClick={onReplay}
          aria-label="Replay the catch"
          className="px-3 py-1.5 text-[10px] tracking-[0.16em]"
        >
          ↻ replay
        </NeonButton>
      </div>
    </div>
  );

  return (
    <HeroShell
      id="hero-shot-withheld"
      index="01"
      eyebrow="HERO SHOT · THE CATCH"
      badge="live · proof-gated settlement"
      badgeTone="emerald"
      headline={
        <>
          Catch a lie.{" "}
          <span className="text-emerald">Pay</span>{" "}
          <span className="text-danger">exactly $0</span>.
        </>
      }
      sub={
        <>
          Every claim in the deliverable is checked against the source document.
          One unsupported claim trips the gate — the whole job is rejected, the
          fabricator&rsquo;s node gets a red <span className="text-danger">✗</span>{" "}
          and{" "}
          <span className="text-fg">no coin moves</span>. $0 settles.
        </>
      }
      metrics={METRICS}
      visual={visual}
      visualSide="right"
    />
  );
}
