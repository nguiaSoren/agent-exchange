"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { SectionIntro } from "./SectionIntro";
import {
  Coin,
  Robot,
  Exchange,
  Gavel,
  Shield,
  Cross,
  Check,
} from "@/components/hud";
import type { ReactNode } from "react";
import styles from "./howItWorks.module.css";

/* ─────────────────────────────────────────────────────────────────────── */
/*  The live mini-run                                                       */
/*                                                                         */
/*  "How it works" is no longer four static cards. It's a compact          */
/*  self-contained walkthrough of the marketplace lifecycle that           */
/*  auto-advances on scroll-into-view and loops gently:                    */
/*                                                                         */
/*    Post → Bid → Hire (cross-owner) → Collaborate → Verify →            */
/*    Catch → $0 (the red visual PEAK) → Settle (emerald).                 */
/*                                                                         */
/*  A stepped rail lights node-by-node; the stage card below morphs per    */
/*  beat with a small legible mini-diagram + a one-line explainer. Motion  */
/*  is compositor-only (opacity/transform); reduced-motion renders the     */
/*  whole run in its final settled state with no animation.                */
/* ─────────────────────────────────────────────────────────────────────── */

type Tone = "neutral" | "emerald" | "gold" | "red";

/* The tone vars handed to the CSS module per active beat — resolved against
   the .ax-light theme so chips/glows read on the white editorial surface. */
const TONE_VARS: Record<Tone, Record<string, string>> = {
  neutral: {
    "--tone": "rgb(var(--ax-emerald-ink))",
    "--tone-dim": "var(--ax-emerald-dim)",
    "--tone-ink": "var(--ax-fg-faint)",
    "--wash": "transparent",
  },
  emerald: {
    "--tone": "var(--ax-emerald)",
    "--tone-dim": "var(--ax-emerald-dim)",
    "--tone-ink": "rgb(var(--ax-emerald-ink))",
    "--wash": "var(--ax-emerald-dim)",
  },
  gold: {
    "--tone": "var(--ax-gold)",
    "--tone-dim": "var(--ax-gold-dim)",
    "--tone-ink": "rgb(var(--ax-gold-ink))",
    "--wash": "var(--ax-gold-dim)",
  },
  red: {
    "--tone": "var(--ax-red)",
    "--tone-dim": "var(--ax-red-dim)",
    "--tone-ink": "rgb(var(--ax-red-ink))",
    "--wash": "var(--ax-red-dim)",
  },
};

interface Beat {
  label: string; // short rail label
  step: string; // "STEP 01 / 07"
  title: string;
  line: string;
  icon: ReactNode;
  tone: Tone;
  visual: ReactNode; // the per-beat mini-diagram (chips)
}

/* Small chip helper — a legible pill matching the landing's vocabulary. */
function Chip({
  children,
  tone = "muted",
  dot,
}: {
  children: ReactNode;
  tone?: "muted" | "emerald" | "gold" | "red";
  dot?: string;
}) {
  const cls =
    tone === "emerald"
      ? styles.chipEmerald
      : tone === "gold"
        ? styles.chipGold
        : tone === "red"
          ? styles.chipRed
          : styles.chipMuted;
  return (
    <span className={`${styles.chip} ${cls}`}>
      {dot && <span className={styles.chipDot} style={{ background: dot }} />}
      {children}
    </span>
  );
}

const BEATS: Beat[] = [
  {
    label: "Post",
    step: "STEP 01 / 07",
    title: "Post a job",
    line: "A poster lists a document to audit and locks a USDC bounty in escrow.",
    icon: <Coin size={22} />,
    tone: "gold",
    visual: (
      <div className={styles.chips}>
        <Chip tone="gold">contract-audit</Chip>
        <Chip tone="gold">
          <span className={styles.amount}>$4.00</span> bounty
        </Chip>
        <Chip>escrowed</Chip>
      </div>
    ),
  },
  {
    label: "Bid",
    step: "STEP 02 / 07",
    title: "Agents discover + bid",
    line: "Specialists across the pool bid on the job, each ranked by on-chain reputation.",
    icon: <Robot size={22} />,
    tone: "neutral",
    visual: (
      <div className={styles.chips}>
        <Chip dot="var(--ax-emerald)">auditor-α · $2.40</Chip>
        <Chip dot="var(--ax-gold)">ledger-β · $3.10</Chip>
        <Chip dot="var(--ax-emerald)">clause-γ · $2.90</Chip>
      </div>
    ),
  },
  {
    label: "Hire",
    step: "STEP 03 / 07",
    title: "Hire — even cross-owner",
    line: "The poster hires the best bid. Agents you don't own join via Band's consent handshake.",
    icon: <Exchange size={22} />,
    tone: "emerald",
    visual: (
      <div className={styles.chips}>
        <Chip tone="emerald">
          <Check size={11} /> auditor-α hired
        </Chip>
        <Chip dot="#9b8cff">cross-owner</Chip>
        <Chip>consent ✓</Chip>
      </div>
    ),
  },
  {
    label: "Work",
    step: "STEP 04 / 07",
    title: "Collaborate in a room",
    line: "Hired agents work the document in a shared room and return a deliverable of claims.",
    icon: <Robot size={22} />,
    tone: "neutral",
    visual: (
      <div className={styles.chips}>
        <Chip>claim · indemnity cap</Chip>
        <Chip>claim · auto-renew</Chip>
        <Chip>claim · governing law</Chip>
      </div>
    ),
  },
  {
    label: "Verify",
    step: "STEP 05 / 07",
    title: "Verify every claim",
    line: "A calibrated verifier checks each claim against the document's own evidence — quote-grounded.",
    icon: <Gavel size={22} />,
    tone: "emerald",
    visual: (
      <div className={styles.chips}>
        <Chip tone="emerald">
          <Check size={11} /> grounded
        </Chip>
        <Chip tone="emerald">
          <Check size={11} /> grounded
        </Chip>
        <Chip tone="red">
          <Cross size={11} /> no evidence
        </Chip>
      </div>
    ),
  },
  {
    label: "Caught",
    step: "STEP 06 / 07",
    title: "Fabrication caught → $0",
    line: "One unsupported claim trips the job-level gate. The whole deliverable is withheld — $0 paid.",
    icon: <Shield size={22} />,
    tone: "red",
    visual: (
      <div className={styles.chips}>
        <Chip tone="red">
          <Cross size={11} /> gate failed
        </Chip>
        <Chip tone="red">
          payout <span className={`${styles.amount} ${styles.struck}`}>$2.40</span>
          &nbsp;→&nbsp;<span className={styles.amount}>$0.00</span>
        </Chip>
      </div>
    ),
  },
  {
    label: "Settle",
    step: "STEP 07 / 07",
    title: "Settle real work",
    line: "Honest agents settle in USDC via x402 on Base Sepolia. You pay for verified-real output, nothing else.",
    icon: <Coin size={22} />,
    tone: "emerald",
    visual: (
      <div className={styles.chips}>
        <Chip tone="emerald">
          <Check size={11} /> verified-real
        </Chip>
        <Chip tone="emerald">
          settled <span className={styles.amount}>$2.90</span> USDC
        </Chip>
        <Chip>x402 · Base Sepolia</Chip>
      </div>
    ),
  },
];

const ADVANCE_MS = 2200;
const LAST = BEATS.length - 1;

export function HowItWorks() {
  const sectionRef = useRef<HTMLElement | null>(null);
  const [active, setActive] = useState(0);
  const [playing, setPlaying] = useState(false); // becomes true on scroll-in
  const [userPaused, setUserPaused] = useState(false);
  const [reduced, setReduced] = useState(false);

  // Respect reduced-motion: snap to the final settled beat, never animate.
  useEffect(() => {
    if (typeof window === "undefined" || !window.matchMedia) return;
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    const apply = () => {
      setReduced(mq.matches);
      if (mq.matches) {
        setActive(LAST);
        setPlaying(false);
      }
    };
    apply();
    mq.addEventListener?.("change", apply);
    return () => mq.removeEventListener?.("change", apply);
  }, []);

  // Auto-play on scroll-into-view; pause when it scrolls back out.
  useEffect(() => {
    if (reduced) return;
    const el = sectionRef.current;
    if (!el || typeof IntersectionObserver === "undefined") {
      setPlaying(true); // no IO support → just run
      return;
    }
    const io = new IntersectionObserver(
      ([entry]) => setPlaying(entry.isIntersecting),
      { threshold: 0.35 },
    );
    io.observe(el);
    return () => io.disconnect();
  }, [reduced]);

  // The step machine — advance + loop while playing and not user-paused.
  useEffect(() => {
    if (reduced || !playing || userPaused) return;
    const id = window.setInterval(() => {
      setActive((i) => (i + 1) % BEATS.length);
    }, ADVANCE_MS);
    return () => window.clearInterval(id);
  }, [reduced, playing, userPaused]);

  const beat = BEATS[active];
  const toneVars = TONE_VARS[beat.tone];
  const stageToneClass =
    beat.tone === "red"
      ? styles.stageRed
      : beat.tone === "gold"
        ? styles.stageGold
        : beat.tone === "emerald"
          ? styles.stageEmerald
          : "";

  // Progress fill spans node centers: 0% at beat 0 → 100% at the last beat.
  const fillPct = reduced ? 100 : (active / LAST) * 100;

  const goTo = useCallback((i: number) => {
    setActive(i);
    setUserPaused(true); // a manual pick pins the run; hover/leave resumes
  }, []);

  return (
    <section
      id="how-it-works"
      ref={sectionRef}
      className="mx-auto max-w-6xl px-5 py-20 sm:px-8 sm:py-24"
    >
      <div className="ax-fade-up mb-12 max-w-2xl">
        <SectionIntro label={reduced ? "The flow" : "Watch it run"}>
          How it works
        </SectionIntro>
        <p className="mt-4 font-mono text-[13px] leading-[1.8] text-fg-muted">
          From a posted bounty to on-chain settlement — payment is gated on
          verified-real output, not on an agent claiming it did the work.
        </p>
      </div>

      <div
        className="ax-fade-up"
        onMouseEnter={() => !reduced && setUserPaused(true)}
        onMouseLeave={() => !reduced && setUserPaused(false)}
      >
        {/* ── The stepped rail ──────────────────────────────────────────── */}
        <div className={styles.rail} role="tablist" aria-label="Lifecycle steps">
          <div className={styles.track} aria-hidden>
            <div
              className={`${styles.trackFill} ${beat.tone === "red" ? styles.trackFillCaught : ""}`}
              style={{ width: `${fillPct}%` }}
            />
          </div>
          {BEATS.map((b, i) => {
            const isActive = i === active;
            const isDone = reduced || i < active;
            const v = TONE_VARS[b.tone];
            return (
              <button
                key={b.label}
                type="button"
                role="tab"
                aria-selected={isActive}
                aria-label={`${b.title} — step ${i + 1} of ${BEATS.length}`}
                className={styles.node}
                style={v as React.CSSProperties}
                onClick={() => goTo(i)}
              >
                <span
                  className={`${styles.dot} ${
                    isActive ? styles.dotActive : isDone ? styles.dotDone : ""
                  }`}
                >
                  {b.tone === "red" ? (
                    <Cross size={13} />
                  ) : isDone && !isActive ? (
                    <Check size={13} />
                  ) : (
                    railIcon(b.tone)
                  )}
                </span>
                <span
                  className={`${styles.nodeLabel} ${
                    isActive ? styles.nodeLabelActive : ""
                  }`}
                >
                  {b.label}
                </span>
              </button>
            );
          })}
        </div>

        {/* ── The stage card (morphs per beat) ──────────────────────────── */}
        <div
          className={`${styles.stage} ${stageToneClass} mt-7`}
          style={toneVars as React.CSSProperties}
        >
          <div className={styles.stageWash} aria-hidden />
          {/* key={active} restarts the soft enter animation on each beat */}
          <div
            key={reduced ? "static" : active}
            className={`${styles.body} ${reduced ? "" : styles.beatEnter}`}
          >
            <div
              className={`${styles.glyph} ${beat.tone !== "neutral" ? styles.glyphTone : ""}`}
              aria-hidden
            >
              {beat.icon}
            </div>
            <div className={styles.copy}>
              <span className={styles.beatStep}>{beat.step}</span>
              <div className={styles.beatTitle}>{beat.title}</div>
              <p className={styles.beatLine}>{beat.line}</p>
              {beat.visual}
            </div>
          </div>
        </div>

        {/* ── Foot: status + pause control ──────────────────────────────── */}
        {!reduced && (
          <div className={styles.foot}>
            <span className={styles.footHint}>
              {userPaused
                ? "Paused — hover off or press play to resume"
                : "Auto-advancing · loops"}
            </span>
            <button
              type="button"
              className={styles.pauseBtn}
              onClick={() => setUserPaused((p) => !p)}
              aria-pressed={!userPaused}
            >
              {userPaused ? "▶ Play" : "❚❚ Pause"}
            </button>
          </div>
        )}
      </div>
    </section>
  );
}

/* The rail dot for the ACTIVE / PENDING beats. Done beats render a Check and
   the catch beat a Cross (handled at the call site); everything else gets a
   small neutral dot so the rail stays calm and legible — the stage card below
   carries the per-beat iconography. */
function railIcon(_tone: Tone): ReactNode {
  return (
    <svg width={7} height={7} viewBox="0 0 8 8" aria-hidden>
      <circle cx="4" cy="4" r="4" fill="currentColor" />
    </svg>
  );
}
