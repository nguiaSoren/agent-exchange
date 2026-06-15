"use client";

import type { AnchorHTMLAttributes, ReactNode } from "react";
import { scrollIntoFullView } from "@/lib/scroll";

/**
 * ScrollLink — an in-page anchor that smooth-scrolls to its target.
 * We can't set `scroll-behavior: smooth` globally (locked layout/css), so we
 * handle it per-link, honoring `prefers-reduced-motion` (jumps instantly then).
 *
 * `fullView` frames the WHOLE target (e.g. the arena) — centred if it fits, else
 * bottom-aligned so its bottom corners show — instead of top-aligning it.
 */
export function ScrollLink({
  href,
  children,
  fullView = false,
  runDemo = false,
  ...rest
}: AnchorHTMLAttributes<HTMLAnchorElement> & {
  href: string;
  children: ReactNode;
  fullView?: boolean;
  /**
   * `runDemo` makes this link START the live demo (identical to clicking "Run
   * job"): it dispatches the `ax:run-demo` event the Dashboard listens for. The
   * run's own handler collapses the console and scrolls the arena into view, so
   * the CTA and the Run button land at the exact same position with the demo
   * actually playing.
   */
  runDemo?: boolean;
}) {
  return (
    <a
      href={href}
      onClick={(e) => {
        if (!href.startsWith("#")) return;
        e.preventDefault();
        if (runDemo) {
          window.dispatchEvent(new CustomEvent("ax:run-demo"));
          history.replaceState(null, "", href);
          return;
        }
        const el = document.getElementById(href.slice(1));
        if (!el) return;
        if (fullView) {
          scrollIntoFullView(el);
        } else {
          const reduce = window.matchMedia(
            "(prefers-reduced-motion: reduce)"
          ).matches;
          el.scrollIntoView({
            behavior: reduce ? "auto" : "smooth",
            block: "start",
          });
        }
        history.replaceState(null, "", href);
      }}
      {...rest}
    >
      {children}
    </a>
  );
}
