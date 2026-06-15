import { LiveDot } from "./LiveDot";

/**
 * Eyebrow — a mono, uppercase, wide-tracked label. The HUD's section/data
 * caption. Optional pulsing live dot for "this is streaming" sections.
 */
export function Eyebrow({
  children,
  live = false,
  tone = "muted",
  className = "",
}: {
  children: React.ReactNode;
  /** Show a leading pulsing live dot. */
  live?: boolean;
  /** Dot + accent tone when live. */
  tone?: "emerald" | "gold" | "red" | "muted";
  className?: string;
}) {
  // White-led: the label is muted (neutral, theme-able) by default. An
  // accent color is applied only when this eyebrow is BOTH `live` AND given a
  // semantic tone — so accents stay reserved for meaningful, streaming rows.
  const accent =
    tone === "emerald"
      ? "text-emerald-glow"
      : tone === "gold"
        ? "text-gold"
        : tone === "red"
          ? "text-danger"
          : "text-fg-muted";
  const colorClass = live && tone !== "muted" ? accent : "text-fg-muted";
  return (
    <span
      className={`inline-flex items-center gap-2 font-mono text-[10px] font-medium uppercase tracking-[0.22em] ${colorClass} ${className}`}
    >
      {live && <LiveDot tone={tone === "muted" ? "emerald" : tone} size={6} />}
      {children}
    </span>
  );
}
