/**
 * Neon Arcade HUD icon set — one consistent stroke (1.75), 24×24 grid,
 * round caps/joins. Inherit color via `currentColor`. NO emojis anywhere.
 * Folds in / restyles the prior components/Icons.tsx set.
 */

interface IconProps {
  size?: number;
  className?: string;
  strokeWidth?: number;
}

function base(size: number, className?: string) {
  return {
    width: size,
    height: size,
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeLinecap: "round" as const,
    strokeLinejoin: "round" as const,
    className,
    "aria-hidden": true,
  };
}

/* ── Verdict glyphs ──────────────────────────────────────────────── */
export function Check({ size = 16, className, strokeWidth = 1.9 }: IconProps) {
  return (
    <svg {...base(size, className)} strokeWidth={strokeWidth}>
      <path d="M4.5 12.5 9.5 17.5 19.5 6.5" />
    </svg>
  );
}

export function Tilde({ size = 16, className, strokeWidth = 1.9 }: IconProps) {
  return (
    <svg {...base(size, className)} strokeWidth={strokeWidth}>
      <path d="M4 13.5c1.5-3 3.5-3 5 0s3.5 3 5 0 3.5-3 5 0" />
    </svg>
  );
}

export function Cross({ size = 16, className, strokeWidth = 1.9 }: IconProps) {
  return (
    <svg {...base(size, className)} strokeWidth={strokeWidth}>
      <path d="M6.5 6.5 17.5 17.5M17.5 6.5 6.5 17.5" />
    </svg>
  );
}

/* ── Market / motion ─────────────────────────────────────────────── */
export function Exchange({ size = 16, className, strokeWidth = 1.75 }: IconProps) {
  return (
    <svg {...base(size, className)} strokeWidth={strokeWidth}>
      <path d="M4 8h13l-3-3M20 16H7l3 3" />
    </svg>
  );
}

export function ArrowRight({ size = 16, className, strokeWidth = 1.75 }: IconProps) {
  return (
    <svg {...base(size, className)} strokeWidth={strokeWidth}>
      <path d="M4 12h15M13 6l6 6-6 6" />
    </svg>
  );
}

export function ArrowUpRight({ size = 14, className, strokeWidth = 1.75 }: IconProps) {
  return (
    <svg {...base(size, className)} strokeWidth={strokeWidth}>
      <path d="M7 17 17 7M9 7h8v8" />
    </svg>
  );
}

export function Bolt({ size = 16, className, strokeWidth = 1.75 }: IconProps) {
  return (
    <svg {...base(size, className)} strokeWidth={strokeWidth}>
      <path d="M13 2.5 5 13.5h6l-2 8 8-11h-6z" />
    </svg>
  );
}

/* ── Money ───────────────────────────────────────────────────────── */
export function Coin({ size = 16, className, strokeWidth = 1.6 }: IconProps) {
  return (
    <svg {...base(size, className)} strokeWidth={strokeWidth}>
      <circle cx="12" cy="12" r="8" />
      <path d="M12 8.5v7M10 10.5h2.5a1.5 1.5 0 0 1 0 3H10h3" />
    </svg>
  );
}

/* ── Verify / authority ──────────────────────────────────────────── */
export function Gavel({ size = 16, className, strokeWidth = 1.75 }: IconProps) {
  return (
    <svg {...base(size, className)} strokeWidth={strokeWidth}>
      <path d="M14.5 4.5 19 9M16.75 6.75 9.5 14M5 20h9" />
      <path d="M7 11.5 11.5 16l-3 3-4.5-4.5z" />
    </svg>
  );
}

export function Shield({ size = 16, className, strokeWidth = 1.75 }: IconProps) {
  return (
    <svg {...base(size, className)} strokeWidth={strokeWidth}>
      <path d="M12 3 5 6v5c0 4 3 6.5 7 8 4-1.5 7-4 7-8V6z" />
      <path d="M9 12l2 2 4-4" />
    </svg>
  );
}

/* ── Time / status ───────────────────────────────────────────────── */
export function Clock({ size = 16, className, strokeWidth = 1.75 }: IconProps) {
  return (
    <svg {...base(size, className)} strokeWidth={strokeWidth}>
      <circle cx="12" cy="12" r="8.5" />
      <path d="M12 7.5V12l3 2" />
    </svg>
  );
}

export function Robot({ size = 16, className, strokeWidth = 1.6 }: IconProps) {
  return (
    <svg {...base(size, className)} strokeWidth={strokeWidth}>
      <rect x="5" y="8" width="14" height="10" rx="2.5" />
      <path d="M12 4.5V8M8 4.5h8" />
      <circle cx="9.5" cy="13" r="1.1" fill="currentColor" stroke="none" />
      <circle cx="14.5" cy="13" r="1.1" fill="currentColor" stroke="none" />
    </svg>
  );
}

/* ── Primitive dots / stars ──────────────────────────────────────── */
export function Dot({ size = 8, className }: IconProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 8 8" aria-hidden className={className}>
      <circle cx="4" cy="4" r="4" fill="currentColor" />
    </svg>
  );
}

export function Star({
  size = 13,
  className,
  filled = false,
}: IconProps & { filled?: boolean }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill={filled ? "currentColor" : "none"}
      stroke="currentColor"
      strokeWidth={1.4}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      aria-hidden
    >
      <path d="M12 3.5l2.6 5.27 5.82.85-4.21 4.1.99 5.79L12 16.77l-5.2 2.74.99-5.79-4.21-4.1 5.82-.85z" />
    </svg>
  );
}

/* ── Verdict glyph picker (keyed off lib/ui Glyph) ───────────────── */
export function VerdictGlyph({
  glyph,
  size = 14,
  className,
}: {
  glyph: "check" | "tilde" | "cross";
  size?: number;
  className?: string;
}) {
  if (glyph === "check") return <Check size={size} className={className} />;
  if (glyph === "tilde") return <Tilde size={size} className={className} />;
  return <Cross size={size} className={className} />;
}
