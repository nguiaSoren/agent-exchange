/**
 * BandMark — the real Band logo MARK (the green/cyan robot face) on a transparent
 * background. `band.svg` is a horizontal lockup (mark + a dark-navy "BAND" wordmark
 * that vanishes on the dark page), so we render the full transparent SVG and crop to
 * its left square (the mark) with an overflow box. One asset, no white box.
 */
export function BandMark({
  size = 48,
  className = "",
}: {
  /** Rendered mark size in px (square). */
  size?: number;
  className?: string;
}) {
  return (
    <span
      className={`relative block shrink-0 overflow-hidden ${className}`}
      style={{ width: size, height: size }}
      aria-hidden
    >
      {/* The SVG is ~533×144; at height=size it's ~3.7×size wide, so the left
          `size` px (clipped by the box) is exactly the circular mark. */}
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        src="/sponsors/band.svg"
        alt="Band"
        style={{ height: size, width: "auto", maxWidth: "none", display: "block" }}
      />
    </span>
  );
}
