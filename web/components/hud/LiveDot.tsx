/**
 * LiveDot — a small pulsing status dot. Compositor-only opacity pulse
 * (honors reduced-motion via the .ax-breathe guard in globals.css).
 */

type DotTone = "emerald" | "gold" | "red" | "muted";

// Accent dots keep their fixed neon hue (a live dot means the same thing in
// every theme). The neutral `muted` dot reads the theme-able faint channel so
// it stays visible on a light surface.
const TONE: Record<DotTone, string> = {
  emerald: "#2bff9a",
  gold: "#ffc233",
  red: "#ff3b5c",
  muted: "rgb(var(--ax-fg-faint-rgb))",
};

export function LiveDot({
  tone = "emerald",
  size = 8,
  pulse = true,
  className = "",
}: {
  tone?: DotTone;
  size?: number;
  pulse?: boolean;
  className?: string;
}) {
  const color = TONE[tone];
  return (
    <span
      aria-hidden
      className={`relative inline-flex shrink-0 ${className}`}
      style={{ width: size, height: size }}
    >
      {pulse && (
        <span
          className="ax-pulse absolute inset-0 rounded-full"
          style={{ background: color, opacity: 0.55, filter: "blur(1px)" }}
        />
      )}
      <span
        className="relative inline-block rounded-full"
        style={{
          width: size,
          height: size,
          background: color,
          boxShadow: `0 0 8px -1px ${color}`,
        }}
      />
    </span>
  );
}
