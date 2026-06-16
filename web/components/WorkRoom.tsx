"use client";

import { useEffect, useRef } from "react";
import type { RoomLine } from "@/lib/runState";
import { Avatar } from "./Avatar";
import { HudPanel } from "@/components/hud";
import { BandMark } from "./landing/BandMark";

/** Senders that are orchestration roles (the market/reporter), not ring agents. */
function isSystemSender(sender: string): boolean {
  const s = sender.toLowerCase();
  return s.includes("coordinator") || s.includes("reporter") || s.includes("market");
}

/**
 * Render a room line with @mentions emphasised as routing chips — the visible
 * "deterministic @mention routing" Band markets. A mention of another agent
 * reads as a hand-off target, so it gets a bordered emerald chip; everything
 * else is plain text.
 */
function renderContent(content: string) {
  const parts = content.split(/(@[\w./-]+)/g);
  return parts.map((p, i) =>
    p.startsWith("@") ? (
      <span
        key={i}
        className="rounded-[3px] border border-emerald/40 bg-emerald-dim px-1 py-px font-medium text-emerald-glow"
      >
        {p}
      </span>
    ) : (
      <span key={i}>{p}</span>
    ),
  );
}

/**
 * WorkRoom — the live Band-room transcript. The hero surface for Band's #1
 * primitive (Chat Rooms + @mention routing): each agent's line streams in with
 * its avatar, @mention hand-offs highlighted as routing chips, and the view
 * auto-scrolls to the newest message. Sits beside the arena ring so the run
 * reads as agents CONVERSING in one room, not just spokes into a verifier.
 *
 * `workActive` lifts the panel (emerald border + live pulse) while the team is
 * actually collaborating, so the room owns the eye during the Work phase.
 */
export function WorkRoom({
  room,
  workActive = false,
}: {
  room: RoomLine[];
  /** True while the Work/collaborate stage is active — emphasise the panel. */
  workActive?: boolean;
}) {
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [room.length]);

  const live = room.length > 0;

  return (
    <HudPanel
      eyebrow="BAND ROOM · LIVE TRANSCRIPT"
      live={live}
      tone={workActive ? "emerald" : "default"}
      padded={false}
      className={`flex h-full min-h-[360px] flex-col transition-shadow duration-500 ${
        workActive ? "shadow-glow-emerald" : ""
      }`}
      bodyClassName="flex min-h-0 flex-1 flex-col"
      title={
        <span className="flex items-center gap-2.5">
          <BandMark size={18} />
          WORK ROOM
        </span>
      }
      right={
        <span className="tnum font-mono text-[11px] text-fg-faint">
          {room.length} msg{room.length === 1 ? "" : "s"}
        </span>
      }
    >
      <div className="ax-scroll min-h-0 flex-1 space-y-4 overflow-y-auto px-5 py-5">
        {room.length === 0 && (
          <div className="flex h-full min-h-[200px] flex-col items-center justify-center gap-2 px-6 text-center">
            <BandMark size={30} />
            <span className="font-mono text-[12px] leading-relaxed text-fg-faint">
              The agents&apos; shared Band room. Their messages and{" "}
              <span className="text-emerald-glow">@mention</span> hand-offs stream
              here once the team starts working.
            </span>
          </div>
        )}

        {room.map((line, i) => {
          const isSystem = isSystemSender(line.sender);
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
