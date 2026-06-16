"use client";

import Image from "next/image";
import { NeonButton, LiveDot, Bolt } from "@/components/hud";
import { ScrollLink } from "./ScrollLink";
import { BandMark } from "./BandMark";

// Band is the HOST sponsor (featured as a lockup); the rest are partner prizes.
const PARTNERS = ["x402", "AI/ML API", "Featherless"];

export function Topbar() {
  return (
    <header className="sticky top-0 z-50 border-b border-hud-neutral bg-canvas/95">
      <div className="mx-auto flex max-w-6xl items-center gap-4 px-5 py-3 sm:px-8">
        {/* Wordmark + live */}
        <div className="flex min-w-0 items-center gap-2.5">
          {/* Designed horizontal lockup (light page → -light variant). */}
          <Image
            src="/brand/lockup-horizontal-light.svg"
            alt="Agent Exchange"
            width={210}
            height={34}
            priority
          />
          <span className="hidden items-center gap-1.5 rounded-md border border-hud bg-emerald-dim px-2 py-0.5 sm:inline-flex">
            <LiveDot tone="emerald" size={7} />
            <span className="font-mono text-[10px] uppercase tracking-[0.16em] text-emerald">
              Live
            </span>
          </span>
        </div>

        {/* Host-sponsor lockup — the real Band mark leads; partners credited smaller. */}
        <div className="ml-auto hidden items-center gap-3 lg:flex">
          <span className="inline-flex items-center gap-2 rounded-full border border-hud bg-surface px-2.5 py-1">
            <BandMark size={20} />
            <span className="font-mono text-[10px] uppercase tracking-[0.14em] text-fg-muted">
              Built&nbsp;on <span className="font-bold text-fg">Band</span>
            </span>
          </span>
          <span className="flex items-center gap-2 font-mono text-[10px] uppercase tracking-[0.14em] text-fg-faint">
            {PARTNERS.map((s, i) => (
              <span key={s} className="flex items-center gap-2">
                {i > 0 && <span className="text-fg-faint/50">·</span>}
                {s}
              </span>
            ))}
          </span>
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
