"use client";

import { useEffect, useRef, useState } from "react";

/**
 * CountUp — an animated ticking number, rAF-driven so it supports decimals,
 * a prefix ($) and suffix (%), and tabular-nums alignment. Respects
 * prefers-reduced-motion (snaps straight to the value). Re-animates whenever
 * `value` changes (e.g. a settlement total updates).
 */
export function CountUp({
  value,
  duration = 1100,
  decimals = 0,
  prefix = "",
  suffix = "",
  className = "",
}: {
  value: number;
  duration?: number;
  decimals?: number;
  prefix?: string;
  suffix?: string;
  className?: string;
}) {
  const [display, setDisplay] = useState(value);
  const fromRef = useRef(value);
  const rafRef = useRef<number | null>(null);

  useEffect(() => {
    const reduce =
      typeof window !== "undefined" &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    const from = fromRef.current;
    const to = value;
    if (reduce || from === to) {
      setDisplay(to);
      fromRef.current = to;
      return;
    }

    const start = performance.now();
    const ease = (t: number) => 1 - Math.pow(1 - t, 3); // ease-out cubic

    const tick = (now: number) => {
      const t = Math.min(1, (now - start) / duration);
      setDisplay(from + (to - from) * ease(t));
      if (t < 1) {
        rafRef.current = requestAnimationFrame(tick);
      } else {
        fromRef.current = to;
      }
    };
    rafRef.current = requestAnimationFrame(tick);

    return () => {
      if (rafRef.current != null) cancelAnimationFrame(rafRef.current);
    };
  }, [value, duration]);

  return (
    <span className={`tnum ${className}`}>
      {prefix}
      {display.toFixed(decimals)}
      {suffix}
    </span>
  );
}
