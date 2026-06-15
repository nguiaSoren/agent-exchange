"use client";

import { Coin } from "./Icons";

/**
 * CoinFlight — a gold coin that flies from a source to a target (client →
 * worker) on settlement. Position the parent `relative`; this renders an
 * absolutely-positioned coin that translates by (dx, dy) over ~900ms.
 * Under reduced-motion the .ax-coin-flight keyframe collapses, so the coin
 * simply appears at the start point (no flight) — still a clear "paid" mark.
 *
 * `play` keys the animation: pass a value that changes when you want it to
 * fire (e.g. the settlement index) so React remounts and re-runs it.
 */
export function CoinFlight({
  dx = 140,
  dy = 0,
  size = 16,
  delay = 0,
  className = "",
}: {
  /** Horizontal travel in px. */
  dx?: number;
  /** Vertical travel in px. */
  dy?: number;
  size?: number;
  /** Animation delay in ms. */
  delay?: number;
  className?: string;
}) {
  return (
    <span
      aria-hidden
      className={`ax-coin-flight pointer-events-none absolute ${className}`}
      style={{
        ["--ax-coin-x" as string]: `${dx}px`,
        ["--ax-coin-y" as string]: `${dy}px`,
        animationDelay: `${delay}ms`,
        color: "#ffc233",
        filter: "drop-shadow(0 0 6px rgba(255,194,51,0.8))",
      }}
    >
      <Coin size={size} />
    </span>
  );
}
