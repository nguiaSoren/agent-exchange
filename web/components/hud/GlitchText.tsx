/**
 * GlitchText — display text with a chromatic emerald/red glitch on hover
 * (or continuously, via `live`). Uses the .ax-glitch keyframe; reduced-motion
 * disables the animation but keeps the text. Renders Orbitron by default.
 */
export function GlitchText({
  children,
  as: Tag = "span",
  live = false,
  className = "",
}: {
  children: React.ReactNode;
  /** Element tag to render (h1, h2, span…). */
  as?: keyof JSX.IntrinsicElements;
  /** Glitch continuously instead of only on hover. */
  live?: boolean;
  className?: string;
}) {
  return (
    <Tag
      className={`font-display ${live ? "ax-glitch-live" : "ax-glitch"} ${className}`}
    >
      {children}
    </Tag>
  );
}
