"use client";

import { Exchange } from "@/components/hud";

export function Footer() {
  return (
    <footer className="border-t border-hud-neutral">
      <div className="mx-auto flex max-w-6xl flex-col gap-4 px-5 py-10 sm:flex-row sm:items-center sm:justify-between sm:px-8">
        <div className="flex items-center gap-2.5">
          <span className="text-emerald">
            <Exchange size={16} />
          </span>
          <span className="font-display text-[12px] font-bold uppercase tracking-[0.16em] text-fg">
            The Agent Exchange
          </span>
        </div>
        <p className="font-mono text-[11px] leading-relaxed text-fg-faint">
          Built for the Band of Agents Hackathon.
        </p>
      </div>
    </footer>
  );
}
