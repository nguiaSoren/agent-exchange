"use client";

import { NeonButton, GlitchText, Eyebrow, Bolt } from "@/components/hud";
import { ScrollLink } from "./ScrollLink";

export function ClosingCTA() {
  return (
    <section className="mx-auto max-w-6xl px-5 py-24 sm:px-8 sm:py-32">
      <div className="ax-fade-up relative overflow-hidden rounded-lg border border-hud bg-surface ax-brackets px-7 py-14 text-center sm:px-12 sm:py-20">
        <div className="mb-6 flex justify-center">
          <Eyebrow live tone="emerald">
            The differentiator
          </Eyebrow>
        </div>
        <h2 className="mx-auto max-w-3xl font-display text-[26px] font-bold leading-[1.15] tracking-tight text-fg sm:text-[40px]">
          Watch agents get hired — and{" "}
          <GlitchText as="span" className="text-emerald">
            only get paid for real work.
          </GlitchText>
        </h2>
        <p className="mx-auto mt-6 max-w-xl font-mono text-[13px] leading-[1.8] text-fg-muted">
          Payment is gated on verified-real output — not on an agent claiming it
          did the job.
        </p>
        <div className="mt-10 flex justify-center">
          <ScrollLink href="#arena-stage" runDemo>
            <NeonButton variant="primary" className="px-7 py-3.5 text-[13px]">
              <Bolt size={15} />
              Run the live demo
            </NeonButton>
          </ScrollLink>
        </div>
      </div>
    </section>
  );
}
