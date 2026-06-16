"use client";

import { useCallback, useEffect, useRef } from "react";
import dynamic from "next/dynamic";

import { useReplay } from "@/lib/useReplay";
import { NeonButton, LiveDot } from "@/components/hud";
import { WorkRoom } from "@/components/WorkRoom";

/**
 * HERO SHOT — "the regulated domain: audit an insurance payout, catch the bad
 * determination."
 *
 * Track 3 (regulated & high-stakes), staged on the REAL system. The recorded
 * `sim-insurance-claim-seeded-liar` replay is folded through the SAME applyEvent
 * reducer the live dashboard uses, so the Arena ring and the WorkRoom transcript
 * render identically to a live run.
 *
 * Five insurance specialists (Coverage-Scope, Exclusions, Limits & Deductible,
 * Claim-Validity, + a cross-owner Payout-Coverage Auditor) audit a homeowners
 * POLICY + CLAIM — two sources, multi-source verification. They confirm the wind
 * damage is covered and that flood is EXCLUDED; the adjuster's fabricated finding
 * — that the policy covers the rising-water / flood loss — is graded
 * `unsupported`, so the job-level gate fails and the whole payout is withheld:
 * $0 settled, $0.13 withheld, gate_passed=false.
 *
 * Laid out FULL-WIDTH (copy on top, then a console: the full-size arena ring +
 * the live transcript side-by-side, like the live demo) so the WorkRoom
 * transcript — the auditors catching the bad determination — is the point.
 * Auto-plays on scroll-into-view; reduced-motion snaps to the loaded/final frame.
 */

// Arena is heavy and pulls @lobehub/icons (not SSR-safe) — load it client-only,
// mirroring HeroShotRoom / HeroShotWithheld / Dashboard exactly.
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

const REPLAY_URL = "/replays/sim-insurance-claim-seeded-liar.replay.json";

const METRICS: { value: string; label: string; tone: "emerald" | "gold" | "danger" }[] = [
  { value: "policy + claim", label: "two sources · multi-source audit", tone: "gold" },
  { value: "flood excluded", label: "the catch · unsupported payout", tone: "danger" },
  { value: "$0", label: "withheld on a bad payout", tone: "danger" },
];

function prefersReducedMotion(): boolean {
  return (
    typeof window !== "undefined" &&
    !!window.matchMedia &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches
  );
}

export function HeroShotInsurance() {
  const ctl = useReplay({ autoloadUrl: REPLAY_URL, initialSpeed: 3 });

  const sectionRef = useRef<HTMLElement>(null);
  const playedThisEntryRef = useRef(false);
  const ctlRef = useRef(ctl);
  ctlRef.current = ctl;

  // Animate the audit from the top, OR (reduced motion) snap to the $0 final frame.
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
      id="hero-shot-insurance"
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
            Insurance · regulated, high-stakes
          </span>
          <span className="inline-flex items-center gap-2 rounded-full border border-hud-neutral bg-surface px-3 py-1 font-mono text-[10px] uppercase tracking-[0.2em] text-fg-muted">
            <LiveDot tone="red" size={6} />
            gate failed · $0 settled
          </span>
        </div>

        <h2 className="max-w-2xl font-display font-black leading-[1.06] tracking-[-0.02em] text-fg text-[clamp(1.9rem,3.6vw,2.85rem)]">
          Audit an insurance payout.{" "}
          <span className="text-danger">Catch the bad determination.</span>
        </h2>

        <p className="mt-5 max-w-2xl font-mono text-[13.5px] leading-[1.8] text-fg-muted">
          A regulated, high-stakes workflow: a homeowners claim. Five
          specialist agents &mdash; <span className="text-fg">Coverage-Scope</span>,{" "}
          <span className="text-fg">Exclusions</span>,{" "}
          <span className="text-fg">Limits &amp; Deductible</span>,{" "}
          <span className="text-fg">Claim-Validity</span>, plus a cross-owner{" "}
          <span className="text-gold">Payout-Coverage Auditor</span> &mdash; check the
          adjuster&rsquo;s payout determination against{" "}
          <span className="text-fg">both the policy AND the claim</span> (two sources,
          multi-source verification). They confirm the wind damage is covered and that
          flood is <span className="text-danger">expressly excluded</span> &mdash; so when
          the adjuster pays a <span className="text-danger">rising-water / flood loss</span>{" "}
          the policy excludes, that finding grades{" "}
          <span className="text-danger">unsupported</span>, the job-level gate fails, and
          the whole payout is withheld &mdash; <span className="text-danger">$0</span>.
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
                    : m.tone === "danger"
                    ? "text-danger ax-num-glow-red"
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
          policy + claim · flood excluded · gate failed · $0 settled · $0.13 withheld
        </span>
        <NeonButton
          variant="ghost"
          onClick={onReplay}
          aria-label="Replay the audit"
          className="px-3 py-1.5 text-[10px] tracking-[0.16em]"
        >
          ↻ replay
        </NeonButton>
      </div>

      {/* Honesty foot line: the fabricated flood-payout is the disclosed seeded
          verifier test; settlement is Base-Sepolia testnet. */}
      <div className="mt-2 px-1">
        <span className="font-mono text-[10px] tracking-[0.04em] text-fg-faint">
          The flood-payout finding is a disclosed seeded test of the verifier. Testnet
          (Base Sepolia) — no real funds.
        </span>
      </div>
    </section>
  );
}
