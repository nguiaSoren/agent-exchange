"use client";

import type { StageEvent } from "@/lib/events";
import { Check, LiveDot, Cross } from "@/components/hud";

/** Horizontal lifecycle stepper for the run (driven by SSE `stage` events). */
export function StageBar({ stages }: { stages: StageEvent[] }) {
  return (
    <div className="ax-scroll flex flex-wrap items-stretch gap-y-3 overflow-x-auto py-1 sm:flex-nowrap">
      {stages.map((s, i) => {
        const active = s.status === "active";
        const done = s.status === "done";
        const error = s.status === "error";
        const last = i === stages.length - 1;

        return (
          <div key={s.name} className="flex flex-1 items-center">
            {/* Stage node */}
            <div
              className={`ax-press flex shrink-0 items-center gap-2 rounded-md border px-3 py-1.5 transition-colors duration-300 ease-ax-out ${
                active
                  ? "border-emerald bg-emerald-dim shadow-glow-emerald"
                  : done
                    ? "border-hud bg-surface-2"
                    : error
                      ? "border-danger bg-danger-dim"
                      : "border-hud-neutral bg-surface-2"
              }`}
            >
              <span className="flex h-4 w-4 items-center justify-center">
                {done ? (
                  <span className="text-emerald-glow">
                    <Check size={13} />
                  </span>
                ) : error ? (
                  <span className="text-danger">
                    <Cross size={12} />
                  </span>
                ) : active ? (
                  <LiveDot tone="emerald" size={8} />
                ) : (
                  <span className="h-2 w-2 rounded-full bg-fg-faint/50" />
                )}
              </span>
              <span
                className={`whitespace-nowrap font-mono text-[11px] uppercase tracking-[0.1em] transition-colors duration-300 ${
                  active
                    ? "text-emerald-glow"
                    : done
                      ? "text-fg-muted"
                      : error
                        ? "text-danger"
                        : "text-fg-faint"
                }`}
              >
                {s.name}
              </span>
            </div>

            {/* Hairline connector — fills emerald once this stage is done */}
            {!last && (
              <div className="mx-1 h-px min-w-[12px] flex-1 overflow-hidden rounded-full bg-hud-neutral">
                <div
                  className="h-full rounded-full bg-emerald transition-all duration-300 ease-ax-out"
                  style={{
                    width: done ? "100%" : "0%",
                    boxShadow: done ? "0 0 6px -1px rgba(0,214,122,0.8)" : "none",
                  }}
                />
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
