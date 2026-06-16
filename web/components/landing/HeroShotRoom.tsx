"use client";

import { useCallback, useEffect, useRef } from "react";
import dynamic from "next/dynamic";

import { useReplay } from "@/lib/useReplay";
import { NeonButton } from "@/components/hud";
import { WorkRoom } from "@/components/WorkRoom";
import { HeroShell, type HeroMetric } from "./HeroShell";

/**
 * HERO SHOT — "the Band room: agents @mention each other and hand off."
 *
 * Not a mockup: this stages Band's #1 marketing primitive (chat rooms +
 * deterministic @mention routing — the room timeline showing agent-to-agent
 * hand-offs) on the REAL system. The recorded `hero-room-collab` replay is
 * folded through the SAME applyEvent reducer the live dashboard uses, so the
 * WorkRoom transcript and the Arena ring render identically to a live run.
 *
 * The focal surface is the WorkRoom transcript (driven by `ctl.state.room`,
 * lifted while the Work stage is active), with a COMPACT Arena beside it so the
 * node→node @mention hand-off particles fire on the ring as the routed messages
 * stream — @ip-warden ↔ @clause-clerk (does §5 termination revoke the §4
 * license?) and @liability-hawk ↔ @indemnity-owl (the §3-cap vs uncapped-
 * indemnity dispute the verifier later resolves).
 *
 * It auto-plays when scrolled into view (IntersectionObserver), and honours
 * prefers-reduced-motion by snapping straight to the loaded/final frame.
 */

// Arena is heavy and pulls @lobehub/icons (not SSR-safe) — load it client-only,
// mirroring HeroShotWithheld / Dashboard / ReplayDashboard exactly.
const Arena = dynamic(() => import("@/components/arena").then((m) => m.Arena), {
  ssr: false,
  loading: () => (
    <div
      className="flex w-full items-center justify-center"
      style={{ aspectRatio: "1 / 1", maxHeight: 320 }}
    >
      <div
        aria-hidden
        className="rounded-full border border-hud-neutral"
        style={{ width: "45%", aspectRatio: "1 / 1", opacity: 0.4 }}
      />
    </div>
  ),
});

const REPLAY_URL = "/replays/hero-room-collab.replay.json";

const METRICS: HeroMetric[] = [
  { value: "3", label: "frameworks", tone: "emerald" },
  { value: "cross-owner", label: "agents in one room", tone: "gold" },
  { value: "@mention", label: "deterministic routing", tone: "emerald" },
];

function prefersReducedMotion(): boolean {
  return (
    typeof window !== "undefined" &&
    !!window.matchMedia &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches
  );
}

export function HeroShotRoom() {
  const ctl = useReplay({ autoloadUrl: REPLAY_URL, initialSpeed: 2 });

  // The section we watch for scroll-into-view.
  const sectionRef = useRef<HTMLDivElement>(null);

  // Has the current on-screen entry already triggered playback? Reset when the
  // section leaves the viewport, so re-entering replays the moment once more.
  const playedThisEntryRef = useRef(false);

  // Keep the latest controller in a ref so the IntersectionObserver effect can
  // stay mounted once (empty deps) without stale-closing over ctl methods.
  const ctlRef = useRef(ctl);
  ctlRef.current = ctl;

  // Drives the moment: animate the room from the top, OR (reduced motion) snap
  // straight to the final frame so the full transcript + caught state shows.
  const triggerMoment = useCallback(() => {
    const c = ctlRef.current;
    if (c.total === 0) return; // replay not loaded yet — wait for next IO tick
    if (prefersReducedMotion()) {
      c.seek(c.total - 1);
      return;
    }
    c.restart();
    c.play();
  }, []);

  useEffect(() => {
    const el = sectionRef.current;
    if (!el || typeof IntersectionObserver === "undefined") {
      // No IO support: show the populated room statically rather than empty.
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
      c.seek(c.total - 1);
      return;
    }
    c.restart();
    c.play();
  }, []);

  const workActive =
    ctl.state.stages.find((s) => s.status === "active")?.name === "Work";

  const visual = (
    <div ref={sectionRef} className="flex flex-col gap-3">
      <div className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_260px]">
        {/* Focal surface: the live Band-room transcript. */}
        <div className="order-1 min-h-[420px]">
          <WorkRoom room={ctl.state.room} workActive={workActive} />
        </div>

        {/* Compact arena beside it — the node→node @mention hand-off particles
            fire here as the routed messages stream into the room. */}
        <div className="order-2 lg:order-2">
          <div className="ax-court h-full px-2 py-3 sm:px-3 sm:py-4">
            <Arena state={ctl.state} idleHint={null} />
          </div>
        </div>
      </div>

      <div className="flex w-full items-center justify-between px-1">
        <span className="font-mono text-[10px] uppercase tracking-[0.16em] text-fg-faint">
          @mention routing · agent-to-agent hand-offs · one Band room
        </span>
        <NeonButton
          variant="ghost"
          onClick={onReplay}
          aria-label="Replay the room"
          className="px-3 py-1.5 text-[10px] tracking-[0.16em]"
        >
          ↻ replay
        </NeonButton>
      </div>
    </div>
  );

  return (
    <HeroShell
      id="hero-shot-room"
      index="01"
      eyebrow="HERO SHOT · THE BAND ROOM"
      badge="live · one Band room"
      badgeTone="emerald"
      headline={
        <>
          Agents <span className="text-emerald">@mention</span>, hand off, and
          collaborate — in one Band room.
        </>
      }
      sub={
        <>
          Cross-framework, cross-owner agents coordinate through Band&rsquo;s
          deterministic <span className="text-emerald">@mention</span> routing:
          <span className="text-fg"> @ip-warden</span> asks{" "}
          <span className="text-fg">@clause-clerk</span> whether §5 termination
          revokes the §4 license, and{" "}
          <span className="text-fg">@liability-hawk</span> challenges{" "}
          <span className="text-fg">@indemnity-owl</span> on the §3 cap. The
          shared work-room is the ground truth the verifier later grades.
        </>
      }
      metrics={METRICS}
      visual={visual}
      visualSide="right"
    />
  );
}
