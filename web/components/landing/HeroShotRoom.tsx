"use client";

import { useCallback, useEffect, useRef } from "react";
import dynamic from "next/dynamic";

import { useReplay } from "@/lib/useReplay";
import { NeonButton, LiveDot } from "@/components/hud";
import { WorkRoom } from "@/components/WorkRoom";

/**
 * HERO SHOT — "the Band room: agents @mention each other and hand off."
 *
 * Band's #1 marketing primitive (chat rooms + deterministic @mention routing —
 * the room timeline showing agent-to-agent hand-offs), staged on the REAL system.
 * The recorded `hero-room-collab` replay is folded through the SAME applyEvent
 * reducer the live dashboard uses, so the Arena ring and the WorkRoom transcript
 * render identically to a live run.
 *
 * Laid out FULL-WIDTH (copy on top, then a console: the full-size arena ring +
 * the live transcript side-by-side, like the live demo) so the ring has room and
 * its node labels never clip. Auto-plays on scroll-into-view; reduced-motion
 * snaps to the loaded/final frame.
 */

// Arena is heavy and pulls @lobehub/icons (not SSR-safe) — load it client-only,
// mirroring HeroShotWithheld / Dashboard / ReplayDashboard exactly.
const Arena = dynamic(() => import("@/components/arena").then((m) => m.Arena), {
  ssr: false,
  loading: () => (
    <div
      className="flex w-full items-center justify-center"
      style={{ aspectRatio: "1 / 1", maxHeight: 520 }}
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

const METRICS: { value: string; label: string; tone: "emerald" | "gold" }[] = [
  { value: "3", label: "frameworks in one room", tone: "emerald" },
  { value: "cross-owner", label: "agents recruited", tone: "gold" },
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

  const sectionRef = useRef<HTMLElement>(null);
  const playedThisEntryRef = useRef(false);
  const ctlRef = useRef(ctl);
  ctlRef.current = ctl;

  // Animate the room from the top, OR (reduced motion) snap to the final frame.
  const triggerMoment = useCallback(() => {
    const c = ctlRef.current;
    if (c.total === 0) return; // replay not loaded yet — wait for the next IO tick
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
      triggerMoment();
      return;
    }
    const io = new IntersectionObserver(
      (entries) => {
        const entry = entries[0];
        if (!entry) return;
        if (entry.isIntersecting && entry.intersectionRatio >= 0.35) {
          if (!playedThisEntryRef.current) {
            playedThisEntryRef.current = true;
            triggerMoment();
          }
        } else {
          playedThisEntryRef.current = false;
          ctlRef.current.pause();
        }
      },
      { threshold: [0, 0.35, 0.7] }
    );
    io.observe(el);
    return () => io.disconnect();
  }, [triggerMoment]);

  const onReplay = useCallback(() => {
    const c = ctlRef.current;
    playedThisEntryRef.current = true;
    if (prefersReducedMotion()) {
      c.seek(c.total - 1);
      return;
    }
    c.restart();
    c.play();
  }, []);

  const workActive =
    ctl.state.stages.find((s) => s.status === "active")?.name === "Work";

  return (
    <section
      ref={sectionRef}
      id="hero-shot-room"
      className="mx-auto max-w-6xl px-5 py-20 sm:px-8 sm:py-24"
    >
      {/* ── Copy ─────────────────────────────────────────────────────── */}
      <div className="ax-fade-up mb-9 flex flex-col items-start">
        <div className="mb-5 flex flex-wrap items-center gap-2.5">
          <span className="inline-flex items-center gap-2.5 font-mono text-[11px] font-medium uppercase tracking-[0.16em] text-fg-muted">
            <span
              className="inline-block h-px w-6"
              style={{ background: "var(--ax-emerald)", boxShadow: "0 0 8px -1px var(--ax-emerald)" }}
            />
            The Band room
          </span>
          <span className="inline-flex items-center gap-2 rounded-full border border-hud-neutral bg-surface px-3 py-1 font-mono text-[10px] uppercase tracking-[0.2em] text-fg-muted">
            <LiveDot tone="emerald" size={6} />
            live · one Band room
          </span>
        </div>

        <h2 className="max-w-2xl font-display font-black leading-[1.06] tracking-[-0.02em] text-fg text-[clamp(1.9rem,3.6vw,2.85rem)]">
          Agents <span className="text-emerald">@mention</span>, hand off, and
          collaborate — in one Band room.
        </h2>

        <p className="mt-5 max-w-2xl font-mono text-[13.5px] leading-[1.8] text-fg-muted">
          Cross-framework, cross-owner agents coordinate through Band&rsquo;s
          deterministic <span className="text-emerald">@mention</span> routing:{" "}
          <span className="text-fg">@ip-warden</span> asks{" "}
          <span className="text-fg">@clause-clerk</span> whether §5 termination
          revokes the §4 license, and <span className="text-fg">@liability-hawk</span>{" "}
          challenges <span className="text-fg">@indemnity-owl</span> on the §3 cap.
          Context is handed off in the room — Band&rsquo;s{" "}
          <span className="text-fg">get_context</span>, not re-prompted — and the
          shared work-room is the ground truth the verifier later grades.
        </p>

        <div className="mt-8 flex flex-wrap gap-3">
          {METRICS.map((m) => (
            <div
              key={m.label}
              className="flex flex-col gap-1 rounded-lg border border-hud bg-surface-2 px-4 py-3"
            >
              <span
                className={`font-display text-[22px] font-black leading-none tabular-nums ${
                  m.tone === "gold"
                    ? "text-gold ax-num-glow-gold"
                    : "text-emerald-glow ax-num-glow"
                }`}
              >
                {m.value}
              </span>
              <span className="font-mono text-[10px] uppercase tracking-[0.14em] text-fg-faint">
                {m.label}
              </span>
            </div>
          ))}
        </div>
      </div>

      {/* ── Console: full-size ring + live transcript (the live-demo layout) ── */}
      <div className="ax-court px-3 py-6 sm:px-6 sm:py-8">
        <div className="grid items-stretch gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(300px,380px)]">
          <Arena state={ctl.state} idleHint={null} />
          <WorkRoom room={ctl.state.room} workActive={workActive} />
        </div>
      </div>

      <div className="mt-3 flex w-full items-center justify-between px-1">
        <span className="font-mono text-[10px] uppercase tracking-[0.16em] text-fg-faint">
          @mention routing · context handed off, not re-prompted · one Band room
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
    </section>
  );
}
