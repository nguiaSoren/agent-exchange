/**
 * Arena geometry + node-identity unification.
 *
 * The arena draws every agent as a node on a circle around a central JOB +
 * VERIFIER core. Two layers share the SAME coordinates: an SVG layer (edges,
 * particles, coins, verdict paths — vector geometry) under an absolutely
 * positioned HTML layer (the nodes themselves, so React provider logos + text
 * + hover cards render as real HTML). This module is the single source of those
 * coordinates AND the bridge that unifies the two agent-identity spaces:
 *
 *   - pool/room events key agents by HANDLE   ("@liability-hawk")
 *   - bid/hire/finding/settle events key them by WORKER  ("liability")
 *
 * `resolveProvider(workerOrHandle)` (lib/providers) matches BOTH and returns a
 * record with a stable `key`. We build the node list off the pool when present
 * (so live runs with unknown agents still render), falling back to the known
 * provider roster before the pool arrives, and index everything by that stable
 * key so every downstream event maps back to exactly one node.
 */

import {
  PROVIDERS,
  resolveProvider,
  type ProviderRecord,
} from "@/lib/providers";
import type { PoolAgent } from "@/lib/events";
import type { RunState } from "@/lib/runState";

/** A resolved arena node: pool data (if any) fused with its provider record. */
export interface ArenaNode {
  /** Stable identity — the provider record's worker key (or handle fallback). */
  key: string;
  handle: string;
  /** Display label (pool name wins over the provider label). */
  label: string;
  owner: string | null;
  crossOwner: boolean;
  provider: ProviderRecord;
}

/** A node's resolved on-canvas position (shared by the SVG + HTML layers). */
export interface NodePoint {
  x: number;
  y: number;
  /** Angle in radians (for outward-pointing labels / tangents). */
  angle: number;
}

/** The arena's fixed coordinate space; both layers use this viewBox. */
export interface ArenaLayout {
  size: number;
  cx: number;
  cy: number;
  radius: number;
  /** Node radius (the visual disc), used to trim edges to the rim. */
  nodeR: number;
  /** Core radius, used to trim edges to the core rim. */
  coreR: number;
}

/**
 * Compute the layout for `n` nodes inside a square of `size` px. Radius and
 * node size scale down on smaller squares so the ring never overlaps illegibly.
 */
export function computeLayout(size: number, n: number): ArenaLayout {
  const cx = size / 2;
  const cy = size / 2;
  // Node disc scales with the canvas; clamp so it stays legible + non-colliding.
  const nodeR = clamp(size * 0.058, 22, 38);
  const coreR = clamp(size * 0.13, 64, 116);
  // Leave a margin so node discs + their labels never clip the edge.
  const margin = nodeR + Math.max(18, size * 0.05);
  let radius = size / 2 - margin;
  // Guarantee a gap between adjacent node centers (avoid overlap on small n/size).
  if (n > 1) {
    const minGap = nodeR * 2.25;
    const minRadius = minGap / (2 * Math.sin(Math.PI / n));
    radius = Math.max(radius, Math.min(minRadius, size / 2 - margin));
  }
  radius = Math.max(radius, coreR + nodeR + 12);
  return { size, cx, cy, radius, nodeR, coreR };
}

/**
 * Position node `index` of `n`. The first node sits at the top (−90°) and the
 * ring proceeds clockwise, so the visual order matches the roster order.
 */
export function nodePoint(layout: ArenaLayout, index: number, n: number): NodePoint {
  const angle = (index / Math.max(1, n)) * Math.PI * 2 - Math.PI / 2;
  return {
    x: layout.cx + Math.cos(angle) * layout.radius,
    y: layout.cy + Math.sin(angle) * layout.radius,
    angle,
  };
}

/**
 * The point on the edge between a node and the core, trimmed to each rim so an
 * arrow/particle starts at the node's edge and ends at the core's edge (not at
 * their centers). Returns both trimmed endpoints + the raw length.
 */
export function edgePoints(
  layout: ArenaLayout,
  p: NodePoint,
): { x1: number; y1: number; x2: number; y2: number; length: number } {
  const dx = layout.cx - p.x;
  const dy = layout.cy - p.y;
  const dist = Math.hypot(dx, dy) || 1;
  const ux = dx / dist;
  const uy = dy / dist;
  const x1 = p.x + ux * layout.nodeR;
  const y1 = p.y + uy * layout.nodeR;
  const x2 = layout.cx - ux * (layout.coreR + 4);
  const y2 = layout.cy - uy * (layout.coreR + 4);
  return { x1, y1, x2, y2, length: Math.hypot(x2 - x1, y2 - y1) };
}

/**
 * The OFF-RING start point for a cross-owner node's entrance: the same outward
 * angle as the node's ring slot, but pushed BEYOND the ring radius (a multiple of
 * it) so the node visibly crosses INTO the room from outside the org boundary.
 * Returned in px space; used as the CSS keyframe's `from` translate so the node
 * travels across the dashed owner-boundary hint and settles onto its ring slot.
 *
 * `reach` is the fraction of the layout half-size to travel past the ring (so the
 * start sits clearly outside the guide ring but never off-canvas on small sizes).
 */
export function offRingPoint(
  layout: ArenaLayout,
  p: NodePoint,
  reach = 0.42,
): { dx: number; dy: number; radius: number } {
  // Direction = the node's own outward angle (cos/sin of its slot angle).
  const ux = Math.cos(p.angle);
  const uy = Math.sin(p.angle);
  // Push out past the ring by a clamped fraction of the half-size, so the start
  // is beyond the boundary ring yet stays on (or just at) the canvas edge.
  const extra = Math.min(layout.size * reach, layout.size / 2 - layout.radius + layout.nodeR * 0.5);
  return {
    // Delta from the node's final ring position to its off-ring origin.
    dx: ux * extra,
    dy: uy * extra,
    // The boundary-ring radius the node crosses (for the dashed owner hint).
    radius: layout.radius + extra * 0.55,
  };
}

/**
 * A gently-bowed arc BETWEEN two ring nodes, trimmed to each node's rim — the
 * path an agent→agent @mention hand-off particle travels. Returns an SVG path
 * string (a quadratic curve) usable directly as a CSS `offset-path`.
 *
 * The arc bows perpendicular to the chord (a consistent side) so a message
 * visibly *routes across the room* rather than firing a straight laser through
 * the central verifier — reinforcing "agents talking to each other," not "agents
 * reporting to the core."
 */
export function nodeToNodeArc(
  layout: ArenaLayout,
  a: NodePoint,
  b: NodePoint,
): { path: string; length: number } {
  const dx = b.x - a.x;
  const dy = b.y - a.y;
  const dist = Math.hypot(dx, dy) || 1;
  const ux = dx / dist;
  const uy = dy / dist;
  // Trim each end to the node rim so the particle starts/ends at the disc edge.
  const x1 = a.x + ux * layout.nodeR;
  const y1 = a.y + uy * layout.nodeR;
  const x2 = b.x - ux * layout.nodeR;
  const y2 = b.y - uy * layout.nodeR;
  // Control point: the chord midpoint pushed along the chord's perpendicular so
  // the arc bows to one side (≈22% of the chord length). We choose the perpendicular
  // that points AWAY from the core (outward), so the message arcs around the room's
  // edge and never crosses the central verifier — even for near-opposite nodes.
  const mx = (x1 + x2) / 2;
  const my = (y1 + y2) / 2;
  const bow = Math.hypot(x2 - x1, y2 - y1) * 0.22;
  let px = -uy; // a unit perpendicular to the chord
  let py = ux;
  // Flip to whichever perpendicular points outward from the core (cx,cy).
  if (px * (mx - layout.cx) + py * (my - layout.cy) < 0) {
    px = -px;
    py = -py;
  }
  const ctrlX = mx + px * bow;
  const ctrlY = my + py * bow;
  return {
    path: `M ${x1} ${y1} Q ${ctrlX} ${ctrlY} ${x2} ${y2}`,
    length: Math.hypot(x2 - x1, y2 - y1),
  };
}

/**
 * Build the ordered node roster from current run state. Uses the pool once it
 * has arrived (covering live/unknown agents), otherwise the known provider
 * roster so the ring is populated the instant a run starts. Every node carries
 * its stable provider `key` so bids/findings/settlements map back unambiguously.
 */
export function buildNodes(state: RunState): ArenaNode[] {
  if (state.pool.length > 0) {
    return state.pool.map((a: PoolAgent) => {
      // Resolve by the specialty `worker` when present (LIVE agents, whose Band
      // handle differs from the bid's worker key) so the node key + the provider
      // logo match the bid/finding/settlement events; otherwise by handle (sim,
      // which aliases its handles).
      const ref = a.worker || a.handle;
      const provider = resolveProvider(ref);
      return {
        key: provider.key || normalizeKey(ref),
        handle: a.handle,
        label: a.name || provider.label,
        owner: a.owner ?? null,
        crossOwner: !!a.cross_owner,
        provider,
      };
    });
  }
  // Pre-pool: show the known roster as a calm, waiting ring.
  return PROVIDERS.map((provider) => ({
    key: provider.key,
    handle: provider.handle,
    label: provider.label,
    owner: null,
    crossOwner: false,
    provider,
  }));
}

/** Index nodes by their stable key for O(1) event→node resolution. */
export function indexByKey(nodes: ArenaNode[]): Map<string, ArenaNode> {
  const m = new Map<string, ArenaNode>();
  for (const node of nodes) m.set(node.key, node);
  return m;
}

/**
 * Resolve an event's agent reference (worker key OR handle) to the node's
 * stable key, so a bid ("liability") and a pool entry ("@liability-hawk")
 * collapse to one identity. Falls back to a normalized form for unknown agents.
 */
export function keyForRef(ref: string): string {
  const rec = resolveProvider(ref);
  return rec.key || normalizeKey(ref);
}

function normalizeKey(s: string): string {
  return s.trim().toLowerCase().replace(/^@/, "");
}

function clamp(v: number, lo: number, hi: number): number {
  return Math.max(lo, Math.min(hi, v));
}
