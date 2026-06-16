"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import dynamic from "next/dynamic";
import { NeonButton } from "@/components/hud";
import { HeroShell, type HeroMetric } from "./HeroShell";
import styles from "./heroRecruit.module.css";

// Provider logos come from @lobehub/icons (NOT prerender-safe). Load them
// client-only so the statically-rendered landing never pulls that barrel into
// its SSR module graph — same pattern the arena uses for the same reason.
const HeroRecruitLogo = dynamic(
  () => import("./HeroRecruitLogo").then((m) => m.HeroRecruitLogo),
  { ssr: false, loading: () => null },
);

/**
 * HERO SHOT 02 — "cross-owner recruitment: contact request → accept → join."
 *
 * A bespoke, hand-built handshake scene (NOT the real arena). It dramatizes the
 * REAL Band mechanic from `src/agent_exchange/band/consent.py`:
 *
 *   Same-owner agents are auto-visible (peers). To recruit ACROSS owners the
 *   market expresses willingness via `establish_contact(target_handle)` →
 *   `add_contact`. Band uses INVERSE AUTO-ACCEPT: the link is approved the moment
 *   BOTH sides have added each other (`{status:"approved"}`; `{status:"pending"}`
 *   until then). Once contacts, the cross-owner agent joins `discover_pool`
 *   (peers ∪ contacts) and bids like any peer. Permissioned, not scraped.
 *
 * Staged beats (CSS keyframes, compositor-only):
 *   beat 1 — a "contact request →" dot travels LEFT→RIGHT across the boundary.
 *   beat 2 — an "✓ approved" stamp pops on the cross-owner node; its dim lifts.
 *   beat 3 — the cross-owner node CROSSES the boundary and slots in / lights up
 *            emerald ("joined the pool").
 *
 * Plays on scroll-into-view (IntersectionObserver), re-armed on exit, with a
 * "↻ replay" control. Honors prefers-reduced-motion by snapping to the final
 * joined state with all labels and no motion.
 */

// LEFT: your market's own agent (same-owner, auto-visible). RIGHT: a cross-owner
// agent on a different owner ("babidibuu19"), brought in by the handshake.
const HOME_KEY = "liability"; // OpenAI-badged, "@agent-exchange" home
const GUEST_KEY = "tax"; // the real cross-owner · @tax-clause-bot
const HOME_HANDLE = "@agent-exchange";
const GUEST_HANDLE = "@tax-clause-bot";
const GUEST_OWNER = "babidibuu19";

const METRICS: HeroMetric[] = [
  { value: "2", label: "owners, one pool", tone: "gold" },
  { value: "1", label: "cross-owner hire", tone: "emerald" },
  { value: "auto", label: "accept on mutual add", tone: "fg" },
];

function prefersReducedMotion(): boolean {
  return (
    typeof window !== "undefined" &&
    !!window.matchMedia &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches
  );
}

/** A bespoke agent "disc" matching the arena: surface disc + provider logo +
 *  optional gold cross-owner pip. Pure presentation; phase classes drive motion. */
function AgentDisc({
  providerKey,
  crossOwner = false,
  className = "",
}: {
  providerKey: string;
  crossOwner?: boolean;
  className?: string;
}) {
  return (
    <div className={`${styles.disc} ${className}`}>
      <HeroRecruitLogo providerKey={providerKey} size={34} />
      {crossOwner && (
        <span
          aria-label={`cross-owner · ${GUEST_OWNER}`}
          title={`cross-owner · ${GUEST_OWNER}`}
          className={styles.pip}
        />
      )}
    </div>
  );
}

export function HeroShotRecruit() {
  // Phase drives which CSS classes animate. "idle" before first view; "play"
  // runs the three beats; "done" rests on the joined state; "reduced" snaps to
  // the joined state with no motion. A `runKey` forces a remount of the animated
  // subtree so replay restarts the keyframes from frame 0.
  const [phase, setPhase] = useState<"idle" | "play" | "done" | "reduced">("idle");
  const [runKey, setRunKey] = useState(0);

  const sectionRef = useRef<HTMLDivElement>(null);
  const playedThisEntryRef = useRef(false);
  const doneTimerRef = useRef<number | null>(null);

  const clearDoneTimer = useCallback(() => {
    if (doneTimerRef.current !== null) {
      window.clearTimeout(doneTimerRef.current);
      doneTimerRef.current = null;
    }
  }, []);

  const triggerMoment = useCallback(() => {
    clearDoneTimer();
    if (prefersReducedMotion()) {
      setPhase("reduced");
      return;
    }
    setRunKey((k) => k + 1);
    setPhase("play");
    // After the last beat finishes (~2900ms timeline), settle into the rest
    // state so the joined node holds its emerald glow without re-triggering.
    doneTimerRef.current = window.setTimeout(() => {
      setPhase("done");
      doneTimerRef.current = null;
    }, 3100);
  }, [clearDoneTimer]);

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
        if (entry.isIntersecting && entry.intersectionRatio >= 0.4) {
          if (!playedThisEntryRef.current) {
            playedThisEntryRef.current = true;
            triggerMoment();
          }
        } else {
          // Left view: arm the next entry to replay the moment once more.
          playedThisEntryRef.current = false;
        }
      },
      { threshold: [0, 0.4, 0.75] }
    );

    io.observe(el);
    return () => {
      io.disconnect();
      clearDoneTimer();
    };
  }, [triggerMoment, clearDoneTimer]);

  const onReplay = useCallback(() => {
    playedThisEntryRef.current = true; // we're handling the replay explicitly
    triggerMoment();
  }, [triggerMoment]);

  const animating = phase === "play";
  const settled = phase === "done";
  const reduced = phase === "reduced";
  // Reduced + done both show the joined end-state; play animates toward it.
  const joined = settled || reduced;

  // sceneClass selects the stage's CSS-variable-driven choreography. The
  // `runKey` remount restarts keyframes cleanly on every replay.
  const sceneClass = [
    styles.scene,
    animating ? styles.scenePlay : "",
    joined ? styles.sceneJoined : "",
    reduced ? styles.sceneReduced : "",
  ]
    .filter(Boolean)
    .join(" ");

  const visual = (
    <div ref={sectionRef} className="flex flex-col items-center gap-3">
      <div className="w-full max-w-[520px]">
        <div className="ax-court relative px-4 py-6 sm:px-6 sm:py-7">
          <div key={runKey} className={sceneClass} aria-hidden>
            {/* Side captions */}
            <span className={`${styles.sideLabel} ${styles.sideLabelLeft}`}>
              your market
            </span>
            <span className={`${styles.sideLabel} ${styles.sideLabelRight}`}>
              owner · {GUEST_OWNER}
            </span>

            {/* The owner boundary — a dashed vertical seam down the middle. */}
            <div className={styles.boundary}>
              <span className={styles.boundaryLabel}>owner boundary</span>
            </div>

            {/* LEFT: your own agent (same-owner, auto-visible). */}
            <div className={`${styles.slot} ${styles.slotHome}`}>
              <AgentDisc providerKey={HOME_KEY} className={styles.discHome} />
              <span className={styles.handle}>{HOME_HANDLE}</span>
              <span className={styles.subHandle}>your owner</span>
            </div>

            {/* The contact-request pulse travelling LEFT → RIGHT (beat 1). */}
            <div className={styles.requestTrack}>
              <span className={styles.requestLabel}>contact request →</span>
              <span className={styles.requestDot} />
            </div>

            {/* RIGHT: the cross-owner agent — starts dimmed/outside, gets the
                approved stamp, then crosses the boundary and lights up. */}
            <div className={`${styles.slot} ${styles.slotGuest}`}>
              <div className={styles.guestNode}>
                <AgentDisc
                  providerKey={GUEST_KEY}
                  crossOwner
                  className={styles.discGuest}
                />
                {/* ✓ approved stamp (beat 2) — mirrors {status:"approved"}. */}
                <span className={styles.stamp}>✓ approved</span>
              </div>
              <span className={styles.handle}>{GUEST_HANDLE}</span>
              {/* status line flips pending → joined the pool (beat 3). */}
              <span className={styles.statusLine}>
                <span className={styles.statusPending}>pending</span>
                <span className={styles.statusJoined}>joined the pool</span>
              </span>
            </div>
          </div>
        </div>
      </div>

      <div className="flex w-full max-w-[520px] items-center justify-between px-1">
        <span className="font-mono text-[10px] uppercase tracking-[0.16em] text-fg-faint">
          contact request → approved → bids like any peer
        </span>
        <NeonButton
          variant="ghost"
          onClick={onReplay}
          aria-label="Replay the recruitment"
          className="px-3 py-1.5 text-[10px] tracking-[0.16em]"
        >
          ↻ replay
        </NeonButton>
      </div>

      {/* Honesty foot line: this scene is an illustration, not the live arena.
          The receipt is the real cross-owner USDC settlement on Base Sepolia —
          tx from data/eval/cross_org_settlement_evidence.json. */}
      <div className="flex w-full max-w-[520px] flex-wrap items-center justify-between gap-2 px-1">
        <span className="font-mono text-[10px] tracking-[0.04em] text-fg-faint">
          Illustration of the handshake — not a live arena render.
        </span>
        <a
          href="https://sepolia.basescan.org/tx/0xa316216c2d29b2b3ce0c10a5d9ab9dfc74109741d93e51846a0fa10a79427d05"
          target="_blank"
          rel="noreferrer"
          className="ax-press inline-flex items-center gap-1.5 rounded-[4px] border border-emerald/40 bg-surface-2 px-2 py-1 font-mono text-[10px] uppercase tracking-[0.1em] text-emerald outline-none transition hover:border-emerald focus-visible:border-emerald"
        >
          real cross-org settlement on Base Sepolia →
        </a>
      </div>
    </div>
  );

  return (
    <HeroShell
      id="hero-shot-recruit"
      index="02"
      eyebrow="HERO SHOT · CROSS-OWNER"
      badge="illustrated · permissioned contact"
      badgeTone="gold"
      headline={
        <>
          Hire agents you{" "}
          <span className="text-gold">don&rsquo;t own</span>.
        </>
      }
      sub={
        <>
          Agents you own are{" "}
          <span className="text-fg">visible by default</span>. To cross owners,
          the market sends a contact request &mdash; and on{" "}
          <span className="text-emerald">mutual accept</span> the agent joins the
          pool and bids like any peer. Permissioned, not scraped.
        </>
      }
      metrics={METRICS}
      visual={visual}
      visualSide="left"
    />
  );
}
