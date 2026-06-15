"use client";

import type { ReactNode } from "react";
import { LiveDot } from "@/components/hud";

/**
 * HeroShell — the shared chrome for a landing "hero shot" section.
 *
 * Borrows ROGUE's structure (a live pill, a big headline, substance-heavy
 * sub-copy, and a row of metric callouts) but in the Agent Exchange theme
 * (white-editorial page, emerald/red accents). The actual cinematic VISUAL is
 * passed in via `visual` and sits in its own column — the focused mini-arena
 * for the withheld shot, the bespoke handshake scene for the recruit shot.
 *
 * Layout: two columns on lg+ (copy + visual), stacked on mobile. `visualSide`
 * alternates the two sections so the page has rhythm.
 */

export interface HeroMetric {
  value: string;
  label: string;
  tone?: "emerald" | "danger" | "gold" | "fg";
}

const TONE: Record<NonNullable<HeroMetric["tone"]>, string> = {
  emerald: "text-emerald-glow",
  danger: "text-danger",
  gold: "text-gold",
  fg: "text-fg",
};

const TONE_GLOW: Record<NonNullable<HeroMetric["tone"]>, string> = {
  emerald: "ax-num-glow",
  danger: "ax-num-glow-red",
  gold: "ax-num-glow-gold",
  fg: "",
};

function MetricCallout({ value, label, tone = "fg" }: HeroMetric) {
  return (
    <div className="flex flex-col gap-1 rounded-lg border border-hud bg-surface-2 px-4 py-3">
      <span
        className={`font-display text-[26px] font-black leading-none tabular-nums ${TONE[tone]} ${TONE_GLOW[tone]}`}
      >
        {value}
      </span>
      <span className="font-mono text-[10px] uppercase tracking-[0.14em] text-fg-faint">
        {label}
      </span>
    </div>
  );
}

export function HeroShell({
  badge,
  badgeTone = "emerald",
  eyebrow,
  headline,
  sub,
  metrics,
  visual,
  visualSide = "right",
  id,
}: {
  /** Section ordinal shown in the eyebrow, e.g. "01". */
  index: string;
  /** Live-pill copy (ROGUE-style), e.g. "live · proof-gated settlement". */
  badge: string;
  badgeTone?: "emerald" | "gold" | "danger";
  /** Section eyebrow label, e.g. "HERO SHOT · THE CATCH". */
  eyebrow: string;
  /** The big headline (compose with <span className="text-emerald"> accents). */
  headline: ReactNode;
  /** Substance-heavy sub-copy. */
  sub: ReactNode;
  metrics: HeroMetric[];
  /** The cinematic scene for this shot. */
  visual: ReactNode;
  visualSide?: "left" | "right";
  id?: string;
}) {
  const copy = (
    <div className="flex flex-col items-start">
      <div className="mb-5 flex flex-wrap items-center gap-2.5">
        <span className="inline-flex items-center gap-2.5 font-mono text-[11px] font-medium uppercase tracking-[0.16em] text-fg-muted">
          <span
            className="inline-block h-px w-6"
            style={{ background: "var(--ax-emerald)", boxShadow: "0 0 8px -1px var(--ax-emerald)" }}
          />
          {eyebrow}
        </span>
        <span className="inline-flex items-center gap-2 rounded-full border border-hud-neutral bg-surface px-3 py-1 font-mono text-[10px] uppercase tracking-[0.2em] text-fg-muted">
          <LiveDot tone={badgeTone === "danger" ? "red" : badgeTone} size={6} />
          {badge}
        </span>
      </div>

      <h2 className="max-w-xl font-display text-[30px] font-black leading-[1.08] tracking-tight text-fg sm:text-[40px]">
        {headline}
      </h2>

      <p className="mt-6 max-w-lg font-mono text-[13.5px] leading-[1.8] text-fg-muted">
        {sub}
      </p>

      <div className="mt-9 grid w-full max-w-md grid-cols-2 gap-3 sm:grid-cols-3">
        {metrics.map((m) => (
          <MetricCallout key={m.label} {...m} />
        ))}
      </div>
    </div>
  );

  return (
    <section
      id={id}
      className="mx-auto max-w-6xl px-5 py-20 sm:px-8 sm:py-24"
    >
      <div className="grid items-center gap-12 lg:grid-cols-2 lg:gap-16">
        {visualSide === "left" ? (
          <>
            <div className="order-2 lg:order-1">{visual}</div>
            <div className="order-1 lg:order-2">{copy}</div>
          </>
        ) : (
          <>
            {copy}
            <div>{visual}</div>
          </>
        )}
      </div>
    </section>
  );
}
