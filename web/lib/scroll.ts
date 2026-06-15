/**
 * scrollIntoFullView — bring an element FULLY into view, prioritising that its
 * bottom-left / bottom-right corners are visible.
 *
 * Used when the arena becomes the focus (pressing Run on the live demo, or Play
 * on a replay): the viewport should frame the whole arena, not land halfway with
 * the bottom corners + legend cut off.
 *
 * Behaviour:
 *  - If the element already sits fully inside the viewport (with margin), do
 *    nothing — never nudge a user who can already see it.
 *  - If it fits in the viewport, centre it so BOTH top and bottom corners show.
 *  - If it's taller than the viewport, align its BOTTOM (corners visible); the
 *    top scrolls off as needed — UNLESS `align: "top"` is passed, in which case
 *    the TOP is pinned (the job/model + top of the ring stay in frame). Use
 *    "top" when a run STARTS (the action begins at the top — assemble/bid), and
 *    the default (bottom) for the terminal summary (the payoff is at the bottom).
 *  - Honours prefers-reduced-motion (instant jump, no smooth scroll).
 */
export function scrollIntoFullView(
  el: HTMLElement | null,
  { margin = 24, align }: { margin?: number; align?: "top" } = {},
): void {
  if (!el || typeof window === "undefined") return;
  const reduce =
    window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;
  const rect = el.getBoundingClientRect();
  const vh = window.innerHeight;

  // Deterministic: always land at the same canonical position so every trigger
  // (Run job, the landing CTAs) frames the arena identically. (If the target is
  // already there, scrollTo is a no-op anyway.)
  let targetTop: number;
  if (align === "top") {
    // Pin the top: a run begins at the top of the stage (the job + assembling
    // ring), so keep that in frame rather than scrolling past it to the bottom.
    targetTop = window.scrollY + rect.top - margin;
  } else if (rect.height <= vh - margin * 2) {
    // Fits: centre so the top AND bottom corners are visible.
    targetTop = window.scrollY + rect.top - (vh - rect.height) / 2;
  } else {
    // Taller than the viewport: align the bottom so the bottom corners show.
    targetTop = window.scrollY + rect.bottom - vh + margin;
  }

  window.scrollTo({
    top: Math.max(0, targetTop),
    behavior: reduce ? "auto" : "smooth",
  });
}
