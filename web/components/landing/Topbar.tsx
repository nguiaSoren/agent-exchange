"use client";

import { NeonButton, LiveDot, Bolt } from "@/components/hud";
import { ScrollLink } from "./ScrollLink";

const SPONSORS = ["Band", "x402", "AI/ML API", "Featherless"];

export function Topbar() {
  return (
    <header className="sticky top-0 z-50 border-b border-hud-neutral bg-canvas/95">
      <div className="mx-auto flex max-w-6xl items-center gap-4 px-5 py-3 sm:px-8">
        {/* Wordmark + live */}
        <div className="flex min-w-0 items-center gap-2.5">
          {/* Instrument mark — a small emerald block that reads as a logotype tick. */}
          <span
            aria-hidden
            className="inline-block h-3.5 w-3.5 shrink-0 rounded-[3px]"
            style={{
              background:
                "linear-gradient(150deg, var(--ax-emerald-glow), var(--ax-emerald))",
              boxShadow: "0 0 12px -2px var(--ax-emerald)",
            }}
          />
          <span className="font-display text-[14px] font-black uppercase tracking-[0.1em] text-fg sm:text-[16px]">
            Agent&nbsp;Exchange
          </span>
          <span className="hidden items-center gap-1.5 rounded-md border border-hud bg-emerald-dim px-2 py-0.5 sm:inline-flex">
            <LiveDot tone="emerald" size={7} />
            <span className="font-mono text-[10px] uppercase tracking-[0.16em] text-emerald">
              Live
            </span>
          </span>
        </div>

        {/* Sponsor strip */}
        <div className="ml-auto hidden items-center gap-2 font-mono text-[10px] uppercase tracking-[0.14em] text-fg-faint lg:flex">
          {SPONSORS.map((s, i) => (
            <span key={s} className="flex items-center gap-2">
              {i > 0 && <span className="text-fg-faint/50">·</span>}
              {s}
            </span>
          ))}
        </div>

        <ScrollLink href="#arena-stage" runDemo className="ml-auto lg:ml-4">
          <NeonButton variant="primary" className="text-[12px]">
            <Bolt size={14} />
            Watch it run
          </NeonButton>
        </ScrollLink>
      </div>
    </header>
  );
}
