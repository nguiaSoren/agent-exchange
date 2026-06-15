"use client";

import { stars } from "@/lib/ui";
import { Star } from "./Icons";

/**
 * Stars — compact 5-star reputation readout, neon gold on a faint track.
 * Supports a fractional final star via an overflow-clip overlay. `value` 0..1.
 */
export function Stars({
  value,
  size = 12,
  className = "",
}: {
  value: number;
  size?: number;
  className?: string;
}) {
  const { full, frac } = stars(value);
  const pct = (value * 100).toFixed(0);
  return (
    <span
      className={`inline-flex items-center gap-[2px] ${className}`}
      title={`reputation ${pct}%`}
      aria-label={`reputation ${pct} percent`}
    >
      {Array.from({ length: 5 }).map((_, i) => {
        const fill = i < full ? 1 : i === full ? frac : 0;
        return (
          <span key={i} className="relative inline-block leading-none">
            {/* empty track (theme-able neutral so it shows on light too) */}
            <span style={{ color: "rgb(var(--ax-border-neutral-rgb) / 0.2)" }}>
              <Star filled size={size} />
            </span>
            {/* lit overlay, clipped to the fraction */}
            <span
              className="absolute inset-0 overflow-hidden"
              style={{
                width: `${fill * 100}%`,
                color: "#ffc233",
                filter: fill > 0 ? "drop-shadow(0 0 3px rgba(255,194,51,0.7))" : "none",
              }}
            >
              <Star filled size={size} />
            </span>
          </span>
        );
      })}
    </span>
  );
}
