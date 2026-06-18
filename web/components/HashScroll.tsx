"use client";

import { useEffect } from "react";

/**
 * Corrects the initial-load anchor scroll for a deep link like
 * `/#try-it-live`. The browser's native anchor jump fires immediately, BEFORE
 * the hero shots and web fonts above the target finish laying out — then that
 * content grows and pushes the real target a few hundred px below where the
 * browser stopped, so the link lands short (the previous section still showing
 * up top). We re-scroll to the hash target once layout has actually settled.
 *
 * We land the section's CONTENT (its first line, past the section's tall top
 * padding) just below the sticky header — not the padded box top, which would
 * leave the heading ~190px down and push the closing honesty caveat off the
 * bottom. Eating the top padding pulls the "Run it live" eyebrow + heading to
 * the top and gives the caveat the room to show at the bottom of the viewport.
 *
 * The clearance ADAPTS to the screen: it measures the live sticky header's
 * rendered height (the header is ~66px on desktop but ~85px on mobile, so a
 * fixed value would tuck the heading under the taller mobile bar) and lands the
 * heading a small gap below whatever the header actually is. On a viewport too
 * short to show the whole section, pinning the heading just under the header is
 * already the best framing — it shows as much of the closing caveat as fits.
 *
 * It re-runs on the two events that shift content (window `load` = images done,
 * `document.fonts.ready` = web fonts swapped) plus a short trailing timeout, and
 * converges to a no-op once the target already sits at that position, so the
 * repeated calls never jitter.
 */
const HEADER_GAP = 8; // breathing room below the header
const HEADER_CLEARANCE_FALLBACK = 68; // used only if no header is found

export function HashScroll(): null {
  useEffect(() => {
    const hash = window.location.hash;
    if (!hash || hash.length < 2) return;
    const id = decodeURIComponent(hash.slice(1));

    let cancelled = false;
    const correct = () => {
      if (cancelled) return;
      const el = document.getElementById(id);
      if (!el) return;
      const reduce =
        window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;
      // Clear the ACTUAL sticky header (taller on mobile), not a fixed guess.
      const header = document.querySelector("header");
      const headerH = header ? header.getBoundingClientRect().height : 0;
      const clearance =
        headerH > 0 ? headerH + HEADER_GAP : HEADER_CLEARANCE_FALLBACK;
      // Skip the section's own top padding so the heading (not the empty padded
      // box top) lands just under the header.
      const padTop = parseFloat(getComputedStyle(el).paddingTop) || 0;
      const top =
        window.scrollY + el.getBoundingClientRect().top + padTop - clearance;
      window.scrollTo({ top: Math.max(0, top), behavior: reduce ? "auto" : "smooth" });
    };
    const schedule = () =>
      requestAnimationFrame(() => requestAnimationFrame(correct));

    schedule();
    window.addEventListener("load", schedule);
    document.fonts?.ready.then(schedule).catch(() => {});
    const t = window.setTimeout(correct, 700);

    return () => {
      cancelled = true;
      window.removeEventListener("load", schedule);
      window.clearTimeout(t);
    };
  }, []);

  return null;
}
