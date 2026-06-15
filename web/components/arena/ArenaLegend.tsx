"use client";

import { useState } from "react";
import { Featherless } from "@lobehub/icons";
import { PROVIDER_NOTE } from "@/lib/providers";

/**
 * Honesty + sponsor legend. Surfaces the four sponsors with their REAL logos
 * (graceful text-wordmark fallback where a file isn't present) and what each is
 * in the arena, plus the PROVIDER_NOTE honesty caption (models illustrate
 * cross-provider routing — the per-agent assignment is illustrative):
 *   - Band       → the agent network / arena substrate   (/sponsors/band.svg)
 *   - x402       → the payment rail (the gold coins)      (styled wordmark)
 *   - AI/ML API  → a model gateway                        (/sponsors/aimlapi.svg)
 *   - Featherless→ a model gateway                        (@lobehub/icons)
 *
 * Rendered on the light court, so chips read as clean cards on the white field.
 */
export function ArenaLegend() {
  return (
    <div className="relative z-[1] flex flex-col items-center gap-2 text-center">
      <div className="flex flex-wrap items-center justify-center gap-x-2 gap-y-1.5 font-mono text-[10px]">
        <Chip note="agent network" tone="emerald">
          <BandMark />
        </Chip>
        <Chip note="payment rail" tone="gold">
          <X402Mark />
        </Chip>
        <Chip note="model gateway">
          <AimlapiMark />
        </Chip>
        <Chip note="model gateway">
          <span className="inline-flex items-center gap-1.5">
            <Featherless size={13} />
            <span className="font-bold uppercase tracking-[0.1em] text-fg">
              Featherless
            </span>
          </span>
        </Chip>
      </div>
      <p className="max-w-[560px] font-mono text-[9.5px] leading-relaxed text-fg-faint">
        {PROVIDER_NOTE}
      </p>
    </div>
  );
}

/**
 * Band sponsor mark — the real SVG when present, a clean "BAND" wordmark if the
 * file is absent. `onError` swaps to the fallback so a missing asset never shows
 * a broken-image glyph.
 */
function BandMark() {
  const [failed, setFailed] = useState(false);
  if (failed) {
    return (
      <span className="font-bold uppercase tracking-[0.18em] text-emerald-glow">
        BAND
      </span>
    );
  }
  return (
    // eslint-disable-next-line @next/next/no-img-element
    <img
      src="/sponsors/band.svg"
      alt="Band"
      height={13}
      className="h-[14px] w-auto"
      onError={() => setFailed(true)}
    />
  );
}

/** AI/ML API sponsor mark — real SVG when present, "AI/ML API" wordmark else. */
function AimlapiMark() {
  const [failed, setFailed] = useState(false);
  if (failed) {
    return (
      <span className="font-bold uppercase tracking-[0.1em] text-fg">
        AI/ML&nbsp;API
      </span>
    );
  }
  return (
    // eslint-disable-next-line @next/next/no-img-element
    <img
      src="/sponsors/aimlapi.png"
      alt="AI/ML API"
      height={14}
      className="h-[14px] w-auto"
      onError={() => setFailed(true)}
    />
  );
}

/**
 * x402 brand wordmark — branded as the lowercase `x402`. Styled inline (no logo
 * file): a gold-tinted mono wordmark that reads as a small brand mark.
 */
export function X402Mark() {
  return (
    <span className="font-mono text-[11px] font-bold lowercase tracking-tight text-gold">
      x402
    </span>
  );
}

function Chip({
  note,
  tone,
  children,
}: {
  note: string;
  tone?: "emerald" | "gold";
  children: React.ReactNode;
}) {
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full border border-hud-neutral bg-surface px-2.5 py-1">
      <span
        className="inline-flex items-center"
        style={
          tone === "emerald"
            ? { color: "var(--ax-emerald-glow)" }
            : tone === "gold"
              ? { color: "var(--ax-gold)" }
              : { color: "rgb(var(--ax-fg-rgb))" }
        }
      >
        {children}
      </span>
      <span className="text-fg-faint">{note}</span>
    </span>
  );
}
