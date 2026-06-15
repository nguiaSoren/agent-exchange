"use client";

import { useEffect, useState } from "react";
import type { DoneEvent } from "@/lib/events";
import { CountUp, SegmentBar, Check, Cross } from "@/components/hud";
import styles from "./arena.module.css";

/**
 * The terminal payoff HUD, shown once the run finishes. Overlaid at the foot of
 * the arena: gate passed, total settled (emerald CountUp) vs withheld (red
 * CountUp), the pay-fraction bar, and the catch_summary.
 *
 * T2-2 staging sequence:
 *   0 ms  — card scales/fades in via styles.summaryEnter
 * ~120 ms — gate icon/label already visible (no extra delay; it leads naturally)
 *   0 ms  — numbers begin counting from 0 → target over 700 ms
 * 700 ms  — SegmentBar mounts (its ax-bar-fill animation starts here)
 */
export function ArenaSummary({ done }: { done: DoneEvent }) {
  // barVisible gates SegmentBar mounting so ax-bar-fill fires after the count.
  const [barVisible, setBarVisible] = useState(false);

  useEffect(() => {
    const reduced =
      typeof window !== "undefined" &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    if (reduced) {
      // Snap everything to final state immediately.
      setBarVisible(true);
      return;
    }

    const id = window.setTimeout(() => setBarVisible(true), 700);
    return () => window.clearTimeout(id);
  }, []);

  // The make-or-break frame: a PASSED gate reads calm-emerald, a FAILED gate
  // (the catch → $0 withheld) must read ALARM — a saturated red rim + halo so
  // it punches on the light court. Drive both off the locked gate result.
  const failed = !done.gate_passed;
  return (
    <div
      className={`${styles.summaryEnter} ${styles.bubble} pointer-events-auto w-full max-w-[640px] rounded-xl border px-5 py-4`}
      style={{
        borderColor: failed ? "var(--ax-red)" : "var(--ax-emerald)",
        background: "rgb(var(--ax-surface-rgb) / 0.97)",
        boxShadow: failed ? "var(--ax-glow-red)" : "var(--ax-glow-emerald)",
      }}
    >
      {/* Gate icon + label — reads first; already in DOM at t=0 */}
      <div className="flex flex-wrap items-center justify-between gap-x-6 gap-y-3">
        <div className="flex items-center gap-2.5">
          <span
            className="inline-flex h-7 w-7 items-center justify-center rounded-full border"
            style={{
              color: done.gate_passed ? "var(--ax-emerald-glow)" : "var(--ax-red)",
              borderColor: done.gate_passed ? "var(--ax-emerald)" : "var(--ax-red)",
              background: done.gate_passed ? "var(--ax-emerald-dim)" : "var(--ax-red-dim)",
            }}
          >
            {done.gate_passed ? <Check size={16} /> : <Cross size={16} />}
          </span>
          <div>
            <div
              className="font-display text-[13px] font-bold uppercase tracking-[0.05em]"
              style={{ color: failed ? "var(--ax-red)" : "rgb(var(--ax-fg-rgb))" }}
            >
              {done.gate_passed ? "Gate passed" : "Gate failed"}
            </div>
            <div className="font-mono text-[10px] uppercase tracking-[0.14em] text-fg-faint">
              proof-gated settlement
            </div>
          </div>
        </div>

        {/* Numbers — count from 0 over 700 ms; tabular-nums prevents width jitter */}
        <div className="flex items-center gap-6">
          <Stat label="settled" tone="emerald" value={done.total_settled_usd} />
          <Stat label="withheld" tone="red" value={done.total_withheld_usd} />
        </div>
      </div>

      {/* Pay-fraction bar — mounts at 700 ms so ax-bar-fill fires after count */}
      <div className="mt-3.5">
        <div className="mb-1 flex items-center justify-between font-mono text-[10px] uppercase tracking-[0.14em] text-fg-faint">
          <span>pay fraction</span>
          <span className="tabular-nums text-fg-muted">
            {(done.pay_fraction * 100).toFixed(0)}%
          </span>
        </div>
        {barVisible && (
          <SegmentBar value={done.pay_fraction} tone="emerald" variant="smooth" />
        )}
        {/* Placeholder rail shown while bar is pending — keeps layout stable */}
        {!barVisible && (
          <div
            className="h-1.5 w-full overflow-hidden rounded-full"
            style={{ background: "rgb(var(--ax-border-neutral-rgb) / 0.1)" }}
          />
        )}
      </div>

      <p className="mt-3 font-mono text-[10.5px] leading-relaxed text-fg-muted">
        {done.catch_summary}
      </p>
    </div>
  );
}

function Stat({
  label,
  tone,
  value,
}: {
  label: string;
  tone: "emerald" | "red";
  value: number;
}) {
  const color = tone === "emerald" ? "var(--ax-emerald-glow)" : "var(--ax-red)";
  return (
    <div className="text-right">
      <div
        className="font-display text-[20px] font-black leading-none tabular-nums"
        style={{ color }}
      >
        <CountUp value={value} duration={700} prefix="$" decimals={2} />
      </div>
      <div className="mt-1 font-mono text-[9px] uppercase tracking-[0.16em] text-fg-faint">
        {label}
      </div>
    </div>
  );
}
