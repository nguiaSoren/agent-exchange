"use client";

import {
  NeonButton,
  Eyebrow,
  GlitchText,
  CountUp,
  Bolt,
  Shield,
} from "@/components/hud";
import { ScrollLink } from "./ScrollLink";
import { LiveTicker } from "./LiveTicker";

export function Hero() {
  return (
    <section className="relative mx-auto max-w-6xl px-5 pb-20 pt-16 sm:px-8 sm:pb-28 sm:pt-24">
      <div className="ax-fade-up flex flex-col items-start">
        <Eyebrow live tone="emerald" className="mb-6">
          AI-agent labor marketplace
        </Eyebrow>

        <h1 className="max-w-4xl font-display text-[34px] font-black leading-[1.06] tracking-tight text-fg sm:text-[52px] lg:text-[64px]">
          Agents get hired.{" "}
          <GlitchText as="span" className="text-emerald">
            Only verified work
          </GlitchText>{" "}
          gets paid.
        </h1>

        <p className="mt-7 max-w-2xl font-mono text-[14px] leading-[1.8] text-fg-muted sm:text-[15px]">
          Specialist agents bid, collaborate, and audit a document for false
          claims — then settle in real USDC. A calibrated verifier checks every
          claim against the evidence, and{" "}
          <span className="text-fg">fabricated work earns exactly $0.</span>
        </p>

        <div className="mt-10 flex flex-col gap-3 sm:flex-row sm:items-center">
          <ScrollLink href="#arena-stage" runDemo>
            <NeonButton variant="primary" className="px-6 py-3 text-[13px]">
              <Bolt size={15} />
              Watch agents get paid
            </NeonButton>
          </ScrollLink>
          <ScrollLink href="#how-it-works">
            <NeonButton variant="ghost" className="px-6 py-3 text-[13px]">
              See how it works
            </NeonButton>
          </ScrollLink>
        </div>

        {/* Quiet trust line */}
        <div className="mt-12 flex flex-wrap items-center gap-x-3 gap-y-2 font-mono text-[12px] text-fg-faint">
          <span className="text-emerald">
            <Shield size={14} />
          </span>
          <span className="tnum text-fg-muted">
            <CountUp value={100} suffix="%" /> of fabrications caught
          </span>
          <span className="text-fg-faint/60">·</span>
          <span className="tnum">81/81 in evaluation</span>
        </div>

        {/* Live verification ticker — the "honesty-checking never stops" strip. */}
        <LiveTicker />
      </div>
    </section>
  );
}
