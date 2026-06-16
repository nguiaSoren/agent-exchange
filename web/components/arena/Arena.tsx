"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import type { RunState } from "@/lib/runState";
import { scrollIntoFullView } from "@/lib/scroll";
import { LiveDot } from "@/components/hud";
import {
  buildNodes,
  computeLayout,
  keyForRef,
  nodePoint,
  type NodePoint,
} from "./geometry";
import {
  buildNodeVMs,
  nodeStatus,
  vmFor as vmLookup,
  type NodeVM,
  type NodeStatus,
} from "./selectors";
import { ArenaEdges, type EdgeParticle } from "./ArenaEdges";
import { ArenaNode } from "./ArenaNode";
import { ArenaCore } from "./ArenaCore";
import { ArenaSummary } from "./ArenaSummary";
import { ArenaLegend } from "./ArenaLegend";
import { DetailDrawer, type ArenaSelection } from "./DetailDrawer";
import arenaStyles from "./arena.module.css";

/** Senders that are orchestration roles, not ring nodes. */
const NON_NODE_SENDERS = new Set(["@coordinator", "@reporter", "coordinator", "reporter"]);

/**
 * The first @mention in a room line that resolves to ANOTHER ring node — i.e. an
 * agent→agent hand-off target. Returns its node key, or null when the line names
 * no other ring agent (a plain status line). Drives the node→node arc particle.
 */
function mentionTargetKey(
  content: string,
  senderKey: string,
  vms: Map<string, unknown>,
): string | null {
  const mentions = content.match(/@[\w./-]+/g);
  if (!mentions) return null;
  for (const m of mentions) {
    const k = keyForRef(m);
    if (k && k !== senderKey && vms.has(k)) return k;
  }
  return null;
}

function reducedMotion(): boolean {
  return (
    typeof window !== "undefined" &&
    !!window.matchMedia &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches
  );
}

/** The active stage name (the one currently "active"), else null. */
function activeStage(state: RunState): string | null {
  const s = state.stages.find((st) => st.status === "active");
  return s ? s.name : null;
}

/**
 * AGENT ARENA — the centerpiece. A living circle of agent nodes around a central
 * JOB + VERIFIER core; bids, messages, verdicts and coin payments animate
 * between the ring and the core as the run streams. Presentational: it reads the
 * RunState and renders whatever it holds (works in demo AND live mode, and
 * re-renders correctly whether events arrive incrementally or state is full).
 */
export function Arena({
  state,
  idleHint = "Press Run — agents will assemble around the job",
}: {
  state: RunState;
  demoMode?: boolean;
  /** Copy for the pre-run idle hint (below the ring). `null` ⇒ no hint. */
  idleHint?: string | null;
}) {
  // Client-only render gate. The brand logos (@lobehub/icons `.Avatar`) are not
  // safe to prerender on the server, so we render a calm placeholder until the
  // component mounts on the client, then swap in the live arena. Keeps SSR/
  // static export clean without touching the shared provider layer.
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);

  // ── responsive square sizing ──────────────────────────────────────
  const wrapRef = useRef<HTMLDivElement | null>(null);
  const [size, setSize] = useState(640);
  useEffect(() => {
    const el = wrapRef.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver((entries) => {
      const w = entries[0]?.contentRect.width ?? 640;
      // Cap height so the arena fits a laptop viewport; clamp small screens.
      setSize(Math.max(300, Math.min(w, 720)));
    });
    ro.observe(el);
    return () => ro.disconnect();
    // Re-attach once the real (mounted) container replaces the placeholder.
  }, [mounted]);

  // ── derive nodes, geometry, per-node view-models ──────────────────
  const nodes = useMemo(() => buildNodes(state), [state]);
  const n = nodes.length;
  const layout = useMemo(() => computeLayout(size, n), [size, n]);
  const points: NodePoint[] = useMemo(
    () => nodes.map((_, i) => nodePoint(layout, i, n)),
    [layout, nodes, n],
  );
  const vms = useMemo(() => buildNodeVMs(state), [state]);
  const stage = activeStage(state);

  const vmFor = (key: string): NodeVM => vmLookup(vms, key);
  const statusFor = (key: string): NodeStatus => nodeStatus(vmFor(key), stage);

  // ── Staggered node exit ────────────────────────────────────────────
  // When the ring shrinks (the candidate roster narrows to the hired pool),
  // React would unmount the dropped nodes all at once. Instead, snapshot each
  // node's last render inputs and keep the removed ones mounted briefly as
  // `exiting` ghosts so they fade out ONE-BY-ONE (staggered) at their last
  // position — reads as sequential selection on camera. Survivors glide to
  // their new ring slots (the left/top transition on ArenaNode).
  type NodeSnap = {
    node: ReturnType<typeof buildNodes>[number];
    point: NodePoint;
    vm: NodeVM;
    status: NodeStatus;
  };
  const snapshot = useMemo(() => {
    const m = new Map<string, NodeSnap>();
    nodes.forEach((node, i) => {
      m.set(node.key, {
        node,
        point: points[i],
        vm: vmFor(node.key),
        status: statusFor(node.key),
      });
    });
    return m;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [nodes, points, vms, stage]);

  const prevSnapRef = useRef<Map<string, NodeSnap> | null>(null);
  const [exiting, setExiting] = useState<
    Array<NodeSnap & { key: string; exitIndex: number }>
  >([]);
  const exitTimers = useRef<number[]>([]);

  useEffect(() => {
    const prev = prevSnapRef.current;
    prevSnapRef.current = snapshot;
    const curKeys = new Set(nodes.map((nd) => nd.key));
    // Drop any ghost whose key is back in the ring (e.g. scrubbed backward).
    setExiting((cur) => cur.filter((e) => !curKeys.has(e.key)));
    if (!prev || reducedMotion()) return;
    const removed = [...prev.keys()].filter((k) => !curKeys.has(k));
    if (removed.length === 0) return;
    const entries = removed.map((k, i) => ({
      ...(prev.get(k) as NodeSnap),
      key: k,
      exitIndex: i,
    }));
    setExiting((cur) => [
      ...cur.filter((e) => !removed.includes(e.key)),
      ...entries,
    ]);
    const ttl = entries.length * 70 + 400 + 80; // stagger + fade + slack
    const t = window.setTimeout(() => {
      setExiting((cur) => cur.filter((e) => !removed.includes(e.key)));
    }, ttl);
    exitTimers.current.push(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [snapshot]);

  useEffect(() => {
    const list = exitTimers.current;
    return () => list.forEach((t) => window.clearTimeout(t));
  }, []);

  // ── click → detail drawer selection (agent key / core / none) ──────
  const [selection, setSelection] = useState<ArenaSelection>(null);

  // ── transient effects: speaking node, floating bubble, fake-shake ──
  const [speakingKey, setSpeakingKey] = useState<string | null>(null);
  const [bubble, setBubble] = useState<{ key: string; text: string } | null>(null);
  const [fakeKey, setFakeKey] = useState<string | null>(null);
  // T2-1: the "catch" beat — dim everything but the culprit + core while a
  // fabrication lands. Driven off the same signal as fakeKey, held slightly
  // longer (≈900ms) so the dim carries through the 700ms shake/flash.
  const [catchBeat, setCatchBeat] = useState(false);
  // T2-3: the node whose paid coin just landed (pulse ring + chip pop).
  const [paidKey, setPaidKey] = useState<string | null>(null);
  // Cross-owner: a dashed gold "owner boundary" hint sweeps in once when a
  // cross-owner agent is recruited (the node crosses INTO the room across it).
  const [crossBoundary, setCrossBoundary] = useState(false);
  const seenCrossHire = useRef(false);

  // ── particle queue (capped) ───────────────────────────────────────
  const [particles, setParticles] = useState<EdgeParticle[]>([]);
  const seqRef = useRef(0);
  const pushParticle = (
    key: string,
    kind: EdgeParticle["kind"],
    to?: string,
  ) => {
    if (reducedMotion()) return; // reduced-motion: no flying particles
    const seq = ++seqRef.current;
    setParticles((prev) => {
      const next = [...prev, { key, kind, to, seq }];
      return next.length > 10 ? next.slice(next.length - 10) : next; // cap concurrency
    });
    // Self-expire so the array doesn't grow unbounded.
    window.setTimeout(() => {
      setParticles((prev) => prev.filter((p) => p.seq !== seq));
    }, 1300);
  };

  // Track what we've already reacted to (so effects fire only on NEW events).
  const seenBids = useRef<Set<string>>(new Set());
  const seenRoom = useRef<number>(-1);
  const seenCoins = useRef<Set<string>>(new Set());
  const seenFake = useRef<Set<string>>(new Set());
  const seenPaid = useRef<Set<string>>(new Set());
  const timers = useRef<number[]>([]);

  // Reset all transient tracking when a run resets (room cleared, no findings).
  useEffect(() => {
    if (state.room.length === 0 && state.bids.length === 0) {
      seenBids.current.clear();
      seenRoom.current = -1;
      seenCoins.current.clear();
      seenFake.current.clear();
      seenPaid.current.clear();
      setSpeakingKey(null);
      setBubble(null);
      setFakeKey(null);
      setCatchBeat(false);
      setPaidKey(null);
      setCrossBoundary(false);
      seenCrossHire.current = false;
      setParticles([]);
    }
  }, [state.room.length, state.bids.length]);

  // Cross-owner recruit → sweep in the gold "owner boundary" hint once, when a
  // hired worker resolves to a cross-owner node (it crosses INTO the room across
  // the boundary). Reduced-motion: the CSS hides the hint (no travel to imply).
  useEffect(() => {
    if (!state.hire || seenCrossHire.current || reducedMotion()) return;
    const crossKeys = new Set(
      nodes.filter((nd) => nd.crossOwner).map((nd) => nd.key),
    );
    const hiredCross = state.hire.hired.some((h) =>
      crossKeys.has(keyForRef(h.worker)),
    );
    if (!hiredCross) return;
    seenCrossHire.current = true;
    setCrossBoundary(true);
    const t = window.setTimeout(() => setCrossBoundary(false), 1200);
    timers.current.push(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state.hire, nodes]);

  // New bids → a bid particle node→core.
  useEffect(() => {
    for (const b of state.bids) {
      const key = keyForRef(b.worker);
      const tag = `${key}:${b.price_usd}`;
      if (seenBids.current.has(tag)) continue;
      seenBids.current.add(tag);
      pushParticle(key, "bid");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state.bids.length]);

  // New room line → speaking pulse + bubble + message particle (if a node).
  useEffect(() => {
    const room = state.room;
    if (room.length - 1 <= seenRoom.current) return;
    const line = room[room.length - 1];
    seenRoom.current = room.length - 1;
    if (NON_NODE_SENDERS.has(line.sender)) return;
    const key = keyForRef(line.sender);
    if (!vms.has(key)) return; // sender not a ring node
    setSpeakingKey(key);
    setBubble({ key, text: line.content });
    // If the line @mentions another ring agent, fly a hand-off particle
    // sender→target (a routed message in the room). A plain status line gets the
    // speaking pulse + bubble only — no particle to the core, so the Work phase
    // reads as a conversation, not spokes into the verifier.
    const target = mentionTargetKey(line.content, key, vms);
    if (target) pushParticle(key, "message", target);
    const t1 = window.setTimeout(() => setSpeakingKey((k) => (k === key ? null : k)), 1600);
    const t2 = window.setTimeout(() => setBubble((b) => (b?.key === key ? null : b)), 2600);
    timers.current.push(t1, t2);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state.room.length]);

  // Run finished → the GATE PASSED / GATE FAILED summary mounts. Auto-scroll so
  // the verdict + settled/withheld numbers are FULLY visible (the payoff frame).
  // Keyed on state.done: it resets to null on a new run, so this fires once per
  // completed run, when the summary appears. Double-rAF lets the summary mount +
  // the arena relayout settle before we frame it; scrollIntoFullView honours
  // prefers-reduced-motion (jumps instead of animating).
  const summaryRef = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (!state.done) return;
    const id = requestAnimationFrame(() =>
      requestAnimationFrame(() => scrollIntoFullView(summaryRef.current)),
    );
    return () => cancelAnimationFrame(id);
  }, [state.done]);

  // New PAID settlement → coin flies core→node. Withheld → no coin (the point).
  // T2-3: when the coin lands (≈950ms travel), pulse the paid node + pop its
  // chip — a small reward flourish for honest, settled work. Once per worker.
  useEffect(() => {
    for (const s of state.settlements) {
      const key = keyForRef(s.worker);
      if (seenCoins.current.has(key)) continue;
      seenCoins.current.add(key);
      if (s.settled_usd > 0) {
        pushParticle(key, "coin");
        if (!reducedMotion() && !seenPaid.current.has(key)) {
          seenPaid.current.add(key);
          // Land the flourish when the coin arrives, then clear it.
          const tLand = window.setTimeout(() => {
            setPaidKey(key);
            const tClear = window.setTimeout(
              () => setPaidKey((k) => (k === key ? null : k)),
              620,
            );
            timers.current.push(tClear);
          }, 950);
          timers.current.push(tLand);
        }
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state.settlements.length]);

  // New FABRICATED finding → the dramatic one-shot shake on that node.
  useEffect(() => {
    for (const f of state.findings) {
      if (f.verdict !== "unsupported") continue;
      const key = keyForRef(f.worker);
      if (seenFake.current.has(key)) continue;
      seenFake.current.add(key);
      setFakeKey(key);
      const t = window.setTimeout(() => setFakeKey((k) => (k === key ? null : k)), 700);
      timers.current.push(t);
      // T2-1: stage the catch as a moment — dim the rest of the court and hold
      // the spotlight on the culprit + red core ~900ms (past the shake/flash).
      // Skip under reduced motion: the verdict stamp/flash still lands, no dim.
      if (!reducedMotion()) {
        setCatchBeat(true);
        const tb = window.setTimeout(() => setCatchBeat(false), 900);
        timers.current.push(tb);
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state.findings.length]);

  // Cleanup all timers on unmount.
  useEffect(() => {
    const list = timers.current;
    return () => list.forEach((t) => window.clearTimeout(t));
  }, []);

  const idle = !state.running && !state.finished && state.pool.length === 0;
  const diameter = layout.nodeR * 2;

  // Pre-mount placeholder (server + first client paint): a calm empty stage so
  // the layout doesn't jump and SSR never instantiates a brand logo.
  if (!mounted) {
    return (
      <div className="flex flex-col items-center gap-6">
        <div
          className="relative mx-auto flex w-full items-center justify-center"
          style={{ maxWidth: 720, aspectRatio: "1 / 1" }}
        >
          <div
            aria-hidden
            className="rounded-full border border-hud-neutral"
            style={{ width: "55%", aspectRatio: "1 / 1", opacity: 0.4 }}
          />
        </div>
        <ArenaLegend />
      </div>
    );
  }

  return (
    <div className="flex flex-col items-center gap-6">
      {/* The square stage. The SVG edge layer sits under the HTML node layer. */}
      <div
        ref={wrapRef}
        className="relative mx-auto w-full"
        style={{ maxWidth: 720 }}
      >
        <div
          className="relative mx-auto"
          style={{ width: size, height: size }}
          role="img"
          aria-label="Agent arena: a ring of AI agents around a central job and verifier."
        >
          {/* faint guide ring */}
          <div
            aria-hidden
            className="pointer-events-none absolute rounded-full border border-hud-neutral"
            style={{
              left: layout.cx,
              top: layout.cy,
              width: layout.radius * 2,
              height: layout.radius * 2,
              transform: "translate(-50%, -50%)",
              opacity: idle ? 0.5 : 0.8,
            }}
          />

          {/* Cross-owner "owner boundary" hint — a gold dashed ring BEYOND the
              guide ring that sweeps in exactly while a cross-owner agent crosses
              into the room. Marks the org boundary the recruit travels across.
              One-shot (mounted only during the recruit); reduced-motion hides it. */}
          {crossBoundary && (
            <div
              aria-hidden
              className={`${arenaStyles.ownerBoundary} pointer-events-none absolute rounded-full`}
              style={{
                left: layout.cx,
                top: layout.cy,
                width: (layout.radius + Math.min(layout.size * 0.42, layout.size / 2 - layout.radius) * 0.55) * 2,
                height: (layout.radius + Math.min(layout.size * 0.42, layout.size / 2 - layout.radius) * 0.55) * 2,
                border: "1.5px dashed var(--ax-gold)",
                boxShadow: "0 0 24px -8px rgba(255,194,51,0.6)",
              }}
            />
          )}

          <ArenaEdges
            layout={layout}
            nodes={nodes}
            points={points}
            vmFor={vmFor}
            statusFor={statusFor}
            particles={particles}
            spotlightKey={catchBeat ? fakeKey : null}
          />

          <ArenaCore
            layout={layout}
            document={state.document}
            findings={state.findings}
            stageActive={stage}
            finished={state.finished}
            emphasized={catchBeat}
            onSelect={() => setSelection({ kind: "core" })}
          />

          {nodes.map((node, i) => (
            <ArenaNode
              key={node.key}
              node={node}
              point={points[i]}
              layout={layout}
              cx={layout.cx}
              vm={vmFor(node.key)}
              status={statusFor(node.key)}
              index={i}
              diameter={diameter}
              speaking={speakingKey === node.key}
              bubble={bubble?.key === node.key ? bubble.text : null}
              fakeJustCaught={fakeKey === node.key}
              dimmed={catchBeat && node.key !== fakeKey}
              spotlight={catchBeat && node.key === fakeKey}
              justPaid={paidKey === node.key}
              onSelect={() => setSelection({ kind: "agent", key: node.key })}
            />
          ))}

          {/* Dropped-from-the-ring agents, fading out one-by-one in place. */}
          {exiting.map((e) => (
            <ArenaNode
              key={`exit-${e.key}`}
              node={e.node}
              point={e.point}
              layout={layout}
              cx={layout.cx}
              vm={e.vm}
              status={e.status}
              index={0}
              diameter={diameter}
              speaking={false}
              bubble={null}
              fakeJustCaught={false}
              dimmed={catchBeat}
              exiting
              exitIndex={e.exitIndex}
            />
          ))}

        </div>
      </div>

      {/* Idle hint — BELOW the ring (in clear space) so it can never overlap the
          bottom node, and copy is caller-driven (the replay has no Run button). */}
      {idle && idleHint && (
        <div className="pointer-events-none -mt-1 flex justify-center">
          <span className="inline-flex items-center gap-2 rounded-full border border-dashed border-hud-neutral bg-surface px-3 py-1.5 font-mono text-[10px] text-fg-faint">
            <LiveDot tone="muted" size={6} pulse={false} />
            {idleHint}
          </span>
        </div>
      )}

      {/* Terminal summary (under the arena) — opens the core/run detail. */}
      {state.done && (
        <button
          ref={summaryRef}
          type="button"
          onClick={() => setSelection({ kind: "core" })}
          aria-label="Open run detail"
          className="w-full max-w-[640px] cursor-pointer rounded-xl text-left transition-transform duration-200 ease-ax-out hover:-translate-y-0.5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald/60"
        >
          <ArenaSummary done={state.done} />
        </button>
      )}

      {/* Honesty + sponsor legend. */}
      <ArenaLegend />

      {/* Click-through detail drawer (peek = hover card, click = full drawer).
          The whole site is the dark neon HUD now and this subtree already sits
          inside `.ax-court`, so the drawer inherits the dark tokens — no theme
          scope needed. */}
      <div>
        <DetailDrawer
          selection={selection}
          state={state}
          onClose={() => setSelection(null)}
        />
      </div>
    </div>
  );
}

