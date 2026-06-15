/**
 * SegmentBar — a HUD progress / proportion bar in two styles:
 *   segmented (default) — ▰▰▰▱ discrete cells that pop in staggered
 *   smooth              — a single neon fill that animates its width
 * `value` is 0..1. `tone` picks the accent.
 */

type Tone = "emerald" | "gold" | "red";

const FILL: Record<Tone, string> = {
  emerald: "#00d67a",
  gold: "#ffc233",
  red: "#ff3b5c",
};
const GLOW: Record<Tone, string> = {
  emerald: "0 0 8px -1px rgba(0,214,122,0.8)",
  gold: "0 0 8px -1px rgba(255,194,51,0.8)",
  red: "0 0 8px -1px rgba(255,59,92,0.8)",
};

export function SegmentBar({
  value,
  tone = "emerald",
  variant = "segmented",
  segments = 12,
  className = "",
}: {
  value: number;
  tone?: Tone;
  variant?: "segmented" | "smooth";
  /** Cell count for the segmented variant. */
  segments?: number;
  className?: string;
}) {
  const v = Math.max(0, Math.min(1, value));
  const color = FILL[tone];

  if (variant === "smooth") {
    return (
      <div
        className={`h-1.5 w-full overflow-hidden rounded-full ${className}`}
        style={{ background: "rgb(var(--ax-border-neutral-rgb) / 0.1)" }}
      >
        <div
          className="ax-bar-fill h-full rounded-full"
          style={{
            ["--ax-fill-to" as string]: `${Math.round(v * 100)}%`,
            background: color,
            boxShadow: GLOW[tone],
          }}
        />
      </div>
    );
  }

  const lit = Math.round(v * segments);
  return (
    <div className={`flex items-center gap-[3px] ${className}`}>
      {Array.from({ length: segments }).map((_, i) => {
        const on = i < lit;
        return (
          <span
            key={i}
            className="ax-seg-pop h-2.5 flex-1 rounded-[2px]"
            style={{
              // @ts-expect-error CSS custom prop for stagger delay
              "--index": i,
              background: on ? color : "rgb(var(--ax-border-neutral-rgb) / 0.11)",
              boxShadow: on ? GLOW[tone] : "none",
            }}
          />
        );
      })}
    </div>
  );
}
