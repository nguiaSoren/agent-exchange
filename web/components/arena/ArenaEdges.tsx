"use client";

import { useMemo } from "react";
import type { ArenaLayout, ArenaNode, NodePoint } from "./geometry";
import { edgePoints, nodeToNodeArc } from "./geometry";
import type { NodeVM, NodeStatus } from "./selectors";
import styles from "./arena.module.css";

/**
 * The SVG geometry layer that sits UNDER the HTML node layer. It draws, per
 * node, the edge connecting it to the core, plus the in-flight particles
 * (bids, messages, coins) that travel that edge via `offset-path`. All edges
 * share the exact coordinates the HTML nodes use (same viewBox = px space).
 *
 * Edge presence/intensity encodes state:
 *   - idle/bidding → faint hairline
 *   - hired/working/judged → a brighter persistent emerald edge
 *   - paid → emerald; withheld/fake → red
 * Bid particles fly node→core during Bid; message particles during Work; gold
 * coins fly core→node for PAID settlements (none for withheld — the absence is
 * the point).
 */
function reducedMotion(): boolean {
  return (
    typeof window !== "undefined" &&
    !!window.matchMedia &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches
  );
}

export interface EdgeParticle {
  /** Node key the particle belongs to (the SENDER for a message hand-off). */
  key: string;
  kind: "bid" | "message" | "coin";
  /**
   * For a `message` particle that is an agent→agent @mention hand-off: the
   * TARGET node key. When set, the particle arcs node→node (a routed message in
   * the room) instead of flying node→core. Ignored for bid/coin.
   */
  to?: string;
  /** Monotonic id so re-adding the same kind re-triggers the animation. */
  seq: number;
}

export function ArenaEdges({
  layout,
  nodes,
  points,
  vmFor,
  statusFor,
  particles,
  spotlightKey = null,
}: {
  layout: ArenaLayout;
  nodes: ArenaNode[];
  points: NodePoint[];
  vmFor: (key: string) => NodeVM;
  statusFor: (key: string) => NodeStatus;
  particles: EdgeParticle[];
  /** During the catch beat: the culprit's key — every other edge dims back. */
  spotlightKey?: string | null;
}) {
  // Precompute each node's trimmed edge geometry + its SVG path string.
  const edges = useMemo(
    () =>
      nodes.map((node, i) => {
        const e = edgePoints(layout, points[i]);
        // node→core path (used by bid/message particles); reverse for coins.
        const fwd = `M ${e.x1} ${e.y1} L ${e.x2} ${e.y2}`;
        const rev = `M ${e.x2} ${e.y2} L ${e.x1} ${e.y1}`;
        return { key: node.key, e, fwd, rev };
      }),
    [layout, nodes, points],
  );
  const edgeByKey = useMemo(() => {
    const m = new Map<string, (typeof edges)[number]>();
    for (const ed of edges) m.set(ed.key, ed);
    return m;
  }, [edges]);
  // Node key → its on-canvas point, so an agent→agent message can arc directly
  // from the sender node to the @mentioned target node.
  const pointByKey = useMemo(() => {
    const m = new Map<string, NodePoint>();
    nodes.forEach((node, i) => m.set(node.key, points[i]));
    return m;
  }, [nodes, points]);

  return (
    <svg
      className="absolute inset-0 h-full w-full"
      viewBox={`0 0 ${layout.size} ${layout.size}`}
      aria-hidden
      style={{ overflow: "visible" }}
    >
      {/* ── persistent edges ── */}
      {edges.map(({ key, e }) => {
        const status = statusFor(key);
        const { stroke, width, opacity, dashed, active } = edgeStyle(status);
        const len = e.length || 1;
        // Catch beat: every edge but the culprit's fades back so the eye stays
        // on the lie. Gated on motion preference (snap, no fade, when reduced).
        const muted = spotlightKey != null && key !== spotlightKey;
        return (
          <line
            key={`edge-${key}`}
            x1={e.x1}
            y1={e.y1}
            x2={e.x2}
            y2={e.y2}
            stroke={stroke}
            strokeWidth={width}
            strokeOpacity={muted ? opacity * 0.3 : opacity}
            strokeLinecap="round"
            strokeDasharray={dashed ? "2 6" : active ? `${len}` : undefined}
            strokeDashoffset={active ? len : undefined}
            className={active ? styles.edgeDraw : undefined}
            style={
              reducedMotion()
                ? undefined
                : { transition: "stroke-opacity 260ms cubic-bezier(0.16,1,0.3,1)" }
            }
          />
        );
      })}

      {/* ── traveling particles ── */}
      {particles.map((p) => {
        const ed = edgeByKey.get(p.key);
        if (!ed) return null;
        // During the catch beat, dim particles that aren't on the culprit edge.
        const muted = spotlightKey != null && p.key !== spotlightKey;
        if (p.kind === "coin") {
          return (
            <g
              key={`coin-${p.key}-${p.seq}`}
              className={styles.travelCoin}
              style={
                {
                  offsetPath: `path("${ed.rev}")`,
                  ["--dur" as string]: "950ms",
                } as React.CSSProperties
              }
            >
              <circle r={6} fill="#ffc233" opacity={muted ? 0.3 : undefined} />
              {/* Bright gold rim glow so the coin reads as a neon coin on the
                  dark court. */}
              <circle
                r={6}
                fill="none"
                stroke="#ffd56a"
                strokeWidth={0.9}
                strokeOpacity={muted ? 0.3 : 0.7}
              />
            </g>
          );
        }
        // A `message` particle with a target is an agent→agent @mention hand-off:
        // it ARCS node→node (a routed message crossing the room). Otherwise the
        // particle flies node→core along the straight edge (bids; legacy messages).
        const isHandoff = p.kind === "message" && p.to != null;
        let offsetPath = `path("${ed.fwd}")`;
        if (isHandoff) {
          const from = pointByKey.get(p.key);
          const target = pointByKey.get(p.to as string);
          if (!from || !target) return null;
          offsetPath = `path("${nodeToNodeArc(layout, from, target).path}")`;
        }
        // Gold bid particle; bright mint (#2BFF9A) message particle — both pop
        // on the dark court.
        const color = p.kind === "bid" ? "#ffc233" : "#2bff9a";
        return (
          <g
            key={`${p.kind}-${p.key}-${p.to ?? "core"}-${p.seq}`}
            className={styles.travel}
            style={
              {
                offsetPath,
                ["--dur" as string]: p.kind === "bid" ? "760ms" : isHandoff ? "920ms" : "820ms",
              } as React.CSSProperties
            }
          >
            <circle r={p.kind === "bid" ? 4 : 3.4} fill={color} opacity={muted ? 0.3 : undefined} />
            {/* Hand-off particles carry a faint mint halo so a routed @mention
                reads as a distinct "message in flight," not a bid. */}
            {isHandoff && (
              <circle
                r={6}
                fill="none"
                stroke={color}
                strokeWidth={0.8}
                strokeOpacity={muted ? 0.2 : 0.5}
              />
            )}
          </g>
        );
      })}
    </svg>
  );
}

function edgeStyle(status: NodeStatus): {
  stroke: string;
  width: number;
  opacity: number;
  dashed: boolean;
  active: boolean;
} {
  switch (status) {
    case "paid":
      return { stroke: "var(--ax-emerald)", width: 1.6, opacity: 0.85, dashed: false, active: false };
    case "withheld":
      return { stroke: "var(--ax-red)", width: 1.4, opacity: 0.7, dashed: true, active: false };
    case "escalated":
      // Paused for human review — a live cyan edge (governance accent), pulsing
      // (active) so the held connection reads as "awaiting", not abandoned.
      return { stroke: "var(--ax-cyan)", width: 1.5, opacity: 0.78, dashed: false, active: true };
    case "judged":
    case "working":
    case "hired":
      return { stroke: "var(--ax-emerald)", width: 1.5, opacity: 0.7, dashed: false, active: true };
    case "bidding":
      // Idle edge on the dark court: white at low alpha (neutral hairline).
      return { stroke: "rgb(255 255 255 / 1)", width: 1, opacity: 0.22, dashed: true, active: false };
    case "declined":
      return { stroke: "rgb(255 255 255 / 1)", width: 1, opacity: 0.08, dashed: true, active: false };
    default:
      return { stroke: "rgb(255 255 255 / 1)", width: 1, opacity: 0.12, dashed: true, active: false };
  }
}
