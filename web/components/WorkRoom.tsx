"use client";

import { useEffect, useRef } from "react";
import type { RoomLine } from "@/lib/runState";
import { Avatar } from "./Avatar";
import { HudPanel, Robot } from "@/components/hud";

/** Render @mentions with an emerald neon emphasis. */
function renderContent(content: string) {
  const parts = content.split(/(@[\w-]+)/g);
  return parts.map((p, i) =>
    p.startsWith("@") ? (
      <span key={i} className="font-medium text-emerald-glow">
        {p}
      </span>
    ) : (
      <span key={i}>{p}</span>
    )
  );
}

export function WorkRoom({ room }: { room: RoomLine[] }) {
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [room.length]);

  return (
    <HudPanel
      eyebrow="COLLAB · SHARED TRANSCRIPT"
      live={room.length > 0}
      tone="default"
      padded={false}
      title={
        <span className="flex items-center gap-2.5">
          <span className="text-emerald-glow">
            <Robot size={17} />
          </span>
          WORK ROOM
        </span>
      }
      right={
        <span className="tnum font-mono text-[11px] text-fg-faint">
          {room.length} msg{room.length === 1 ? "" : "s"}
        </span>
      }
    >
      <div className="ax-scroll max-h-[440px] space-y-4 overflow-y-auto px-5 py-5">
        {room.length === 0 && (
          <div className="flex h-full min-h-[160px] items-center justify-center px-6 text-center font-mono text-[12px] text-fg-faint">
            The transcript streams here once the team starts working.
          </div>
        )}

        {room.map((line, i) => {
          const isSystem =
            line.sender.includes("coordinator") ||
            line.sender.includes("reporter");
          return (
            <div
              key={line.id}
              className="ax-stagger flex gap-3"
              style={{
                // @ts-expect-error CSS custom prop for stagger delay
                "--index": i,
              }}
            >
              <Avatar seed={line.sender} size={28} />
              <div className="min-w-0 flex-1">
                <div className="mb-1 flex items-baseline gap-2">
                  <span className="font-mono text-[11px] font-medium text-fg-muted">
                    {line.sender}
                  </span>
                  {isSystem && (
                    <span className="rounded-[3px] border border-hud-neutral px-1 py-px font-mono text-[8px] font-medium uppercase tracking-[0.12em] text-fg-faint">
                      system
                    </span>
                  )}
                </div>
                <div
                  className="rounded-md rounded-tl-[3px] border px-3.5 py-2.5 font-mono text-[12.5px] leading-relaxed text-fg-muted"
                  style={{
                    borderColor: isSystem
                      ? "rgba(0,214,122,0.18)"
                      : "rgba(255,255,255,0.06)",
                    background: isSystem
                      ? "rgba(0,214,122,0.06)"
                      : "var(--ax-surface-2)",
                  }}
                >
                  {renderContent(line.content)}
                </div>
              </div>
            </div>
          );
        })}
        <div ref={endRef} />
      </div>
    </HudPanel>
  );
}
