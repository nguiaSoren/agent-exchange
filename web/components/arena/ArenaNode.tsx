"use client";

import { useEffect, useState } from "react";
import { GatewayLogo, ProviderLogo } from "@/components/ProviderLogo";
import { Stars, VerdictGlyph } from "@/components/hud";
import { verdictStyle } from "@/lib/ui";
import { FRAMEWORKS } from "@/lib/providers";
import { offRingPoint, type ArenaLayout, type ArenaNode as ArenaNodeT, type NodePoint } from "./geometry";
import { type NodeVM, type NodeStatus } from "./selectors";
import { NodeHoverCard } from "./NodeHoverCard";
import styles from "./arena.module.css";

/**
 * One agent node on the ring (HTML layer). Renders the brand logo (the
 * cross-provider proof), the handle, reputation stars, a cross-owner marker,
 * and reacts to its status: bidding price tag, hired emerald glow, declined
 * dim, a speaking pulse + transient bubble, a verdict stamp on its rim, and the
 * paid / withheld settlement readout. Hover reveals the rich detail card.
 */
export function ArenaNode({
  node,
  point,
  layout,
  cx,
  vm,
  status,
  index,
  diameter,
  speaking,
  bubble,
  fakeJustCaught,
  dimmed = false,
  spotlight = false,
  justPaid = false,
  onSelect,
  exiting = false,
  exitIndex = 0,
}: {
  node: ArenaNodeT;
  point: NodePoint;
  /** The arena layout — used to compute a cross-owner node's off-ring entrance. */
  layout: ArenaLayout;
  /** The arena center x — used to open the hover card toward open space. */
  cx: number;
  vm: NodeVM;
  status: NodeStatus;
  index: number;
  /** Node disc diameter in px (2 × nodeR). */
  diameter: number;
  /** True while this node is the active speaker in the room. */
  speaking: boolean;
  /** Transient line to show as a floating bubble (or null). */
  bubble: string | null;
  /** Trigger the dramatic one-shot shake when its fabrication is caught. */
  fakeJustCaught: boolean;
  /** Fade this node back during the "catch" beat (it's not the focal point). */
  dimmed?: boolean;
  /** This node IS the caught culprit during the beat — raise + lift it. */
  spotlight?: boolean;
  /** A paid coin just landed here — pulse a ring + pop the settlement chip. */
  justPaid?: boolean;
  /** Click / Enter / Space → open this agent's detail drawer. */
  onSelect?: () => void;
  /** True ⇒ this node was just dropped from the ring; play the staggered fade-out. */
  exiting?: boolean;
  /** Stagger ordinal for the exit fade (so dropped agents leave one-by-one). */
  exitIndex?: number;
}) {
  const [hover, setHover] = useState(false);
  const [pressed, setPressed] = useState(false);

  const dim = status === "declined";
  const hired = ["hired", "working", "judged", "paid", "withheld"].includes(status);
  const worst = vm.worstVerdict;

  // ── Cross-owner recruit pulse ──────────────────────────────────────────
  // A cross-owner agent (one you don't own) gets a brief "joined from @owner →"
  // gold label the moment it's recruited onto the team (status leaves bidding/
  // idle for a hired-ish state). Fires ONCE per node; under reduced motion the
  // label is shown statically present (the CSS snaps it), then cleared on a timer.
  const [recruited, setRecruited] = useState(false);
  const recruitFired = useState(() => ({ done: false }))[0];
  useEffect(() => {
    if (!node.crossOwner || recruitFired.done) return;
    if (!vm.hired) return; // wait for the hire decision to land on this node
    recruitFired.done = true;
    setRecruited(true);
    const t = window.setTimeout(() => setRecruited(false), 2300);
    return () => window.clearTimeout(t);
  }, [node.crossOwner, vm.hired, recruitFired]);

  // ── Filling progress ring ─────────────────────────────────────────────
  // Shows HOW FAR each agent is through its work, resolving one-by-one:
  //  • working               → crawl asymptotically toward ~85% (keyframe)
  //  • working + collabDone   → advance to ~90% (in-room audit landed)
  //  • resolved (verdict in)  → snap to 100% (a quick complete), then fade
  // `resolved` = a finding/settlement has landed, i.e. status left "working".
  const resolved = ["judged", "paid", "withheld"].includes(status);
  // Render the ring for the whole work→resolve arc. We keep it mounted briefly
  // after resolve so the snap-to-100% reads before it fades.
  const showRing = status === "working" || resolved;
  const ringPhase: "work" | "done" | "resolve" = resolved
    ? "resolve"
    : vm.collabDone
      ? "done"
      : "work";
  // SVG geometry: a BOLD ring that sits clearly OUTSIDE the disc rim (its own
  // viewBox is larger than the disc) so it reads as a distinct "loading" ring,
  // not the disc border. Thicker stroke + a glow (applied in CSS) make the work
  // phase unmistakably active.
  const ringStroke = Math.max(3, Math.round(diameter * 0.07));
  const ringSize = Math.round(diameter * 1.18);
  const ringR = ringSize / 2 - ringStroke / 2;
  const ringCirc = 2 * Math.PI * ringR;
  // A flagged drift signal reads as a failure (this agent cheated) — same danger
  // accent as fabrication/withheld. Clean (non-flagged) drifts render NO badge.
  const driftFlagged = vm.drift?.flagged === true;
  const ring = driftFlagged ? "var(--ax-red)" : ringColor(status, worst);

  // The provider this node ACTUALLY routes through. LIVE pool/bid events carry it
  // (folded onto vm.gateway); otherwise fall back to the illustrative record.
  const gateway = vm.gateway ?? node.provider.gateway;

  // Whether THIS node shows a gateway chip — the framework routing pill (non-
  // native, keyed off the illustrative provider gateway) or the native gateway
  // chip (keyed off the effective gateway). Both chips ALREADY print the model
  // name, so when one shows we must NOT also print the standalone model-name line
  // below (that line is the fallback for nodes with no chip — else it duplicates).
  const gatewayChipShown =
    vm.framework === "native"
      ? gateway === "AI/ML API" || gateway === "Featherless"
      : node.provider.gateway === "AI/ML API" ||
        node.provider.gateway === "Featherless";

  // Display handle: LIVE agents carry their real Band handle ("owner/agent", e.g.
  // "nguiasoren/liability-auditor"), which is verbose. For your OWN agents drop the
  // redundant owner prefix → "@liability-auditor". For a CROSS-OWNER agent KEEP the
  // "owner/agent" form ("babidibuu19/tax-clause-bot") — that different owner name is
  // the whole cross-org proof. Demo handles ("@liability-hawk") pass through unchanged.
  const handleLabel = node.crossOwner
    ? node.handle
    : (() => {
        const tail = node.handle.split("/").pop() || node.handle;
        return tail.startsWith("@") ? tail : `@${tail}`;
      })();

  // Open the hover card toward the canvas center (where there's room): a node
  // on the LEFT half opens RIGHT, a node on the RIGHT half opens LEFT.
  const openSide: "left" | "right" = point.x < cx ? "right" : "left";

  // Cross-owner nodes ENTER from beyond the ring (across the owner boundary): the
  // crossEnter keyframe travels from this off-ring origin onto the ring slot, with
  // a gold streak. Same-owner nodes keep the in-place nodeEnter fade.
  const off = node.crossOwner && !exiting ? offRingPoint(layout, point) : null;
  const entranceClass = exiting
    ? styles.nodeExit
    : node.crossOwner
      ? styles.crossEnter
      : styles.nodeEnter;

  return (
    <div
      role={onSelect ? "button" : undefined}
      tabIndex={onSelect ? 0 : undefined}
      aria-label={onSelect ? `Open agent detail: ${node.label} (${node.handle})` : undefined}
      className={`${entranceClass} ${dimmed ? styles.dimmed : ""} absolute ${onSelect && !exiting ? "cursor-pointer focus-visible:outline-none" : ""}`}
      style={{
        left: point.x,
        top: point.y,
        ["--i" as string]: index,
        ["--exit-i" as string]: exitIndex,
        // Off-ring origin for the cross-owner entrance (px deltas from the slot).
        ...(off
          ? {
              ["--cross-dx" as string]: `${off.dx}px`,
              ["--cross-dy" as string]: `${off.dy}px`,
            }
          : {}),
        // Survivors glide to their new ring slot when the roster shrinks; exiting
        // ghosts hold their last position and fade in place.
        transition: exiting
          ? undefined
          : "left 380ms cubic-bezier(0.16,1,0.3,1), top 380ms cubic-bezier(0.16,1,0.3,1)",
        transform: "translate(-50%, -50%)",
        // Spotlit culprit rides above every sibling during the catch beat.
        zIndex: hover ? 50 : spotlight ? 40 : 10,
        pointerEvents: exiting ? "none" : undefined,
      }}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      onFocus={() => setHover(true)}
      onBlur={() => setHover(false)}
      onClick={onSelect}
      onKeyDown={(e) => {
        if (!onSelect) return;
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onSelect();
        }
      }}
    >
      {/* Cross-owner GOLD HALO — a steady gold ring around the WHOLE node so an
          agent you don't own stands out among your own. Sits just outside the
          disc rim. Reduced-motion keeps it on (steady), only the breathe is cut. */}
      {node.crossOwner && (
        <span
          aria-hidden
          className={`${styles.crossHalo} pointer-events-none absolute left-1/2 top-1/2 rounded-full`}
          style={{
            width: diameter + 12,
            height: diameter + 12,
            transform: "translate(-50%, -50%)",
            border: "2px solid var(--ax-gold)",
          }}
        />
      )}

      {/* Recruit pulse — a brief "joined from @owner →" gold label at the moment
          the cross-owner agent is hired across the org boundary. */}
      {node.crossOwner && recruited && (
        <span
          aria-hidden
          className={`${styles.recruitPulse} pointer-events-none absolute left-1/2 top-1/2 z-30 inline-flex items-center gap-1 whitespace-nowrap rounded-full border px-2 py-0.5 font-mono text-[8.5px] font-bold tracking-[0.04em]`}
          style={{
            transform: `translate(-50%, calc(-50% - ${diameter * 0.5 + 24}px))`,
            color: "var(--ax-gold)",
            borderColor: "var(--ax-gold)",
            background: "rgb(var(--ax-canvas-rgb))",
            boxShadow: "0 0 12px -2px rgba(255,194,51,0.8)",
          }}
        >
          joined from @{node.owner ?? "external"} →
        </span>
      )}

      {/* Speaking / judged ping rings (compositor-only; reduced-motion off). */}
      {(speaking || (status === "judged" && !vm.settlement)) && (
        <span
          aria-hidden
          className={`${styles.ping} pointer-events-none absolute left-1/2 top-1/2 rounded-full`}
          style={{
            width: diameter,
            height: diameter,
            border: `1.5px solid ${speaking ? "var(--ax-emerald-glow)" : ring}`,
          }}
        />
      )}

      {/* Paid-settlement ring pulse (one-shot emerald) — fires when a coin lands.
          Mirrors the .ping span sizing/positioning; single-shot via .paidRing. */}
      {justPaid && (
        <span
          aria-hidden
          className={`${styles.paidRing} pointer-events-none absolute left-1/2 top-1/2 rounded-full`}
          style={{
            width: diameter,
            height: diameter,
            border: "1.5px solid var(--ax-emerald-glow)",
          }}
        />
      )}

      {/* "Thinking" pulse — two offset continuous rings while the agent works the
          long collaborate/verify phase, so the node visibly reasons instead of
          sitting frozen. (Suppressed during the transient speaking ping above.) */}
      {status === "working" && !speaking && (
        <>
          <span
            aria-hidden
            className={`${styles.thinking} pointer-events-none absolute left-1/2 top-1/2 rounded-full`}
            style={{ width: diameter, height: diameter, border: "1.5px solid var(--ax-emerald-glow)" }}
          />
          <span
            aria-hidden
            className={`${styles.thinking2} pointer-events-none absolute left-1/2 top-1/2 rounded-full`}
            style={{ width: diameter, height: diameter, border: "1.5px solid var(--ax-emerald-glow)" }}
          />
        </>
      )}

      {/* Filling progress ring — the headline "how far" cue. An SVG arc whose
          stroke-dashoffset advances: a CSS keyframe crawls it asymptotically to
          ~85% while working, a class swap transitions it to ~90% on collabDone,
          and to 100% (a quick complete) on resolve, after which the wrapper
          fades. Compositor-friendly (stroke-dashoffset/opacity). Reduced-motion
          shows a static partial arc (see .progressRing rules). */}
      {showRing && (
        <svg
          aria-hidden
          className={`${styles.progressRing} ${
            ringPhase === "resolve"
              ? styles.progressResolve
              : ringPhase === "done"
                ? styles.progressDone
                : styles.progressWork
          } pointer-events-none absolute left-1/2 top-1/2`}
          width={ringSize}
          height={ringSize}
          viewBox={`0 0 ${ringSize} ${ringSize}`}
          style={{
            // Center over the disc and rotate so the arc starts at 12 o'clock.
            transform: "translate(-50%, -50%) rotate(-90deg)",
            ["--ring-circ" as string]: ringCirc,
            // Glow so the ring pops off the dark court — reads as "alive/working".
            filter: "drop-shadow(0 0 3px var(--ax-emerald-glow))",
          }}
        >
          {/* Faint full track so the un-filled remainder is visible (reads as a
              progress ring, not a lone arc). */}
          <circle
            cx={ringSize / 2}
            cy={ringSize / 2}
            r={ringR}
            fill="none"
            stroke="var(--ax-emerald-glow)"
            strokeWidth={ringStroke}
            opacity={0.16}
          />
          <circle
            cx={ringSize / 2}
            cy={ringSize / 2}
            r={ringR}
            fill="none"
            stroke="var(--ax-emerald-glow)"
            strokeWidth={ringStroke}
            strokeLinecap="round"
            strokeDasharray={ringCirc}
            // Initial offset = empty ring; CSS drives it from here.
            strokeDashoffset={ringCirc}
          />
        </svg>
      )}

      {/* Continuously-rotating spinner head — the unmistakable "actively working"
          motion that runs the ENTIRE think. A live in-room audit is a single long
          (~1-2 min) model call with no intermediate output, so the determinate arc
          would just sit there; this never stops sweeping until the agent's audit
          lands (collabDone) — proving it's alive, not frozen. */}
      {status === "working" && !vm.collabDone && (
        <svg
          aria-hidden
          className={`${styles.workSpinner} pointer-events-none absolute left-1/2 top-1/2`}
          width={ringSize}
          height={ringSize}
          viewBox={`0 0 ${ringSize} ${ringSize}`}
          style={{
            ["--ring-circ" as string]: ringCirc,
            filter: "drop-shadow(0 0 4px var(--ax-emerald-glow))",
          }}
        >
          <circle
            cx={ringSize / 2}
            cy={ringSize / 2}
            r={ringR}
            fill="none"
            stroke="var(--ax-emerald-glow)"
            strokeWidth={ringStroke}
            strokeLinecap="round"
            strokeDasharray={`${ringCirc * 0.25} ${ringCirc}`}
          />
        </svg>
      )}

      {/* The disc — click affordance: lifts + gains a soft ring on hover/focus.
          Press state adds a 0.97 scale (pressed wins over hover). */}
      <div
        className={`${fakeJustCaught ? styles.fakeShake : ""} relative flex flex-col items-center justify-center rounded-full border transition-[opacity,box-shadow,border-color,transform] duration-300`}
        style={{
          width: diameter,
          height: diameter,
          // Spotlit culprit gets a gentle lift (~1.04). It only applies while the
          // disc is NOT actively shaking, so it never fights the fakeShake keyframe
          // (which owns transform during the shake). Press/hover still win.
          transform: `translate(-50%, -50%) ${
            pressed
              ? "scale(0.97)"
              : hover && onSelect
                ? "scale(1.06)"
                : spotlight && !fakeJustCaught
                  ? "scale(1.04)"
                  : "scale(1)"
          }`,
          position: "absolute",
          left: "50%",
          top: "50%",
          opacity: dim ? 0.4 : 1,
          // Dark disc with a hairline ring + a neon glow lift. `--ax-surface-rgb`
          // re-themes to the deep panel under `.ax-court`, so the disc reads dark.
          background: "rgb(var(--ax-surface-rgb))",
          borderColor: ring,
          boxShadow: hover && onSelect
            ? `0 0 0 3px rgb(var(--ax-border-neutral-rgb) / 0.08), ${hired ? glowFor(status, worst) : "0 0 18px -6px rgba(0,214,122,0.35), 0 12px 24px -10px rgba(0,0,0,0.7)"}`
            : spotlight
              ? `0 0 0 2px var(--ax-red), ${glowFor(status, worst)}`
              : hired
                ? glowFor(status, worst)
                : "0 0 12px -6px rgba(0,214,122,0.25), 0 8px 18px -10px rgba(0,0,0,0.6)",
        }}
        onPointerDown={() => setPressed(true)}
        onPointerUp={() => setPressed(false)}
        onPointerLeave={() => setPressed(false)}
      >
        {/* The node's primary mark is always the agent's MODEL brand. The
            sponsor/gateway it routes through is shown in the routing pill below
            (model → gateway), so model brand and partner logo coexist. */}
        <ProviderLogo provider={node.provider} size={Math.round(diameter * 0.42)} />

        {/* Red flash overlay — self-expires via the fakeFlash CSS animation. */}
        {fakeJustCaught && (
          <span
            aria-hidden
            className={styles.fakeFlash}
            style={{
              position: "absolute",
              inset: 0,
              borderRadius: "9999px",
              background: "var(--ax-red)",
              pointerEvents: "none",
            }}
          />
        )}

        {/* Cross-owner accessibility marker — the visual signal is the gold halo
            ring around the node (above); this carries the label for SR/title. */}
        {node.crossOwner && (
          <span
            aria-label={`cross-owner agent · ${node.owner ?? "external"}`}
            title={`cross-owner · ${node.owner ?? "external"}`}
            className="sr-only"
          />
        )}

        {/* Verdict stamp on the rim (toward the core). */}
        {worst && (
          <span
            className={`${styles.stamp} absolute left-1/2 top-1/2 inline-flex items-center justify-center rounded-full border`}
            style={stampStyle(point, diameter, worst)}
          >
            <VerdictGlyph
              glyph={verdictStyle(worst).glyph}
              size={Math.round(diameter * 0.34)}
            />
          </span>
        )}
      </div>

      {/* Behavioral-drift badge (danger) — only on a FLAGGED node. Anchored
          above the disc; reuses the product's failure-state red so a cheating
          agent reads instantly, the same accent as fabrication/withheld. The
          stamp's reveal/pop vocab (.stamp) is killed under reduced-motion. */}
      {driftFlagged && (
        <span
          aria-label={`behavioral drift: ${vm.drift!.summary}`}
          title={vm.drift!.summary}
          className={`${styles.stamp} absolute z-20 inline-flex items-center gap-0.5 whitespace-nowrap rounded-full border px-1.5 py-0.5 font-mono text-[8.5px] font-bold uppercase tracking-[0.08em]`}
          style={{
            left: "50%",
            top: "50%",
            transform: `translate(-50%, calc(-50% - ${diameter * 0.5 + 9}px))`,
            color: "var(--ax-red)",
            borderColor: "var(--ax-red)",
            background: "rgb(var(--ax-canvas-rgb))",
            boxShadow: "0 0 10px -2px var(--ax-red)",
          }}
        >
          ⚠ {vm.drift!.model_switch ? "MODEL SWAP" : "DRIFT"}
        </span>
      )}

      {/* Bid price tag (gold) — floats beside the node while bidding/hired.
          Dropped once a verdict exists so a judged/withheld node doesn't keep
          its stale gold bid tag on screen. */}
      {vm.bid && !vm.settlement && !vm.worstVerdict && (
        <span
          className="absolute whitespace-nowrap rounded-full border border-gold/30 bg-surface px-1.5 py-0.5 font-mono text-[9px] font-bold tabular-nums text-gold"
          style={tagStyle(point, diameter, "price")}
        >
          ${vm.bid.price_usd.toFixed(2)}
        </span>
      )}

      {/* Label band under the disc: handle, then stars/model, then (if settled)
          the settlement chip — STACKED so the handle and the "$0 · WITHHELD" /
          "+$" readout can never collide (they previously overlapped because the
          settlement chip was angular-outward-positioned onto the handle row). */}
      <div
        className="absolute left-1/2 -translate-x-1/2 flex flex-col items-center gap-0.5"
        style={{ top: diameter / 2 + 6, opacity: dim ? 0.5 : 1 }}
      >
        <span className="whitespace-nowrap font-mono text-[10px] font-medium text-fg">
          {handleLabel}
        </span>
        {/* Routing pill — only on NON-native agents. Shows the framework AND the
            full routing relationship as logos: framework label · [model brand] →
            [sponsor/gateway]. So the model logo (Claude/Qwen) and the partner
            logo (AI/ML API / Featherless) COEXIST, connected by an arrow that
            reads "this model, routed through this partner, via the X framework."
            Reuses the node chip vocab; bordered/labelled by the framework accent. */}
        {vm.framework !== "native" && gatewayChipShown && (
            <span
              title={`${FRAMEWORKS[vm.framework].label} agent — runs ${node.provider.model} routed through ${node.provider.gateway}, collaborating via Band`}
              className="flex items-center gap-1 whitespace-nowrap rounded-full border px-1.5 py-0.5"
              style={{
                borderColor: FRAMEWORKS[vm.framework].accent ?? "var(--ax-border-neutral)",
                background: "rgb(var(--ax-surface-rgb))",
              }}
            >
              <span
                className="font-mono text-[8px] font-bold uppercase tracking-[0.06em]"
                style={{ color: FRAMEWORKS[vm.framework].accent ?? "var(--ax-fg-muted)" }}
              >
                {FRAMEWORKS[vm.framework].label}
              </span>
              <span className="text-fg-faint opacity-50" aria-hidden>
                ·
              </span>
              <ProviderLogo provider={node.provider} size={13} title={node.provider.providerLabel} />
              <span className="text-[10px] leading-none text-fg-faint" aria-hidden>
                →
              </span>
              <GatewayLogo gateway={node.provider.gateway} size={13} />
            </span>
          )}
        {/* Native-node gateway chip — uses the EFFECTIVE gateway (a LIVE pool/bid
            gateway folded onto vm.gateway, else the illustrative providers.ts
            value). Shown in BOTH modes so the demo surfaces the AI/ML API +
            Featherless spread as much as a live run does — the legend's honesty
            caption flags the assignment as illustrative. Non-native nodes show
            the gateway in their routing pill above, so they're excluded here (no
            double-render). Reads "claude-haiku · [AI/ML API mark]". */}
        {vm.framework === "native" && gatewayChipShown && (
          <span
            title={`${node.provider.model} routed through ${gateway}, collaborating via Band`}
            className="flex items-center gap-1 whitespace-nowrap rounded-full border px-1.5 py-0.5"
            style={{
              borderColor: "var(--ax-border-neutral)",
              background: "rgb(var(--ax-surface-rgb))",
            }}
          >
            <span className="font-mono text-[8px] font-medium lowercase tracking-[0.04em] text-fg-faint">
              {node.provider.model}
            </span>
            <span className="text-fg-faint opacity-50" aria-hidden>
              ·
            </span>
            <GatewayLogo gateway={gateway} size={13} />
          </span>
        )}
        {status === "working" ? (
          <span
            className={`${styles.thinkLabel} font-mono text-[8.5px] lowercase tracking-[0.08em] text-emerald`}
          >
            analyzing…
          </span>
        ) : vm.bid && !vm.settlement ? (
          <Stars value={vm.bid.reputation} size={9} />
        ) : !vm.settlement && !gatewayChipShown ? (
          // Standalone model name — ONLY when no gateway chip is shown above
          // (the chip already prints the model; else this duplicates it).
          <span className="font-mono text-[8.5px] text-fg-faint">
            {node.provider.model}
          </span>
        ) : null}

        {/* Settlement readout (+$ paid emerald / $0 withheld red) — its own row
            below the handle, centered, with clear spacing. */}
        {vm.settlement && (
          <span
            className={`mt-0.5 whitespace-nowrap rounded-full border px-1.5 py-0.5 font-mono text-[9px] font-bold tabular-nums ${
              justPaid && vm.settlement.settled_usd > 0 ? styles.chipPop : ""
            }`}
            style={{
              color: vm.settlement.settled_usd > 0 ? "var(--ax-emerald-glow)" : "var(--ax-red)",
              borderColor: vm.settlement.settled_usd > 0 ? "var(--ax-emerald)" : "var(--ax-red)",
              background: "rgb(var(--ax-surface-rgb))",
            }}
          >
            {vm.settlement.settled_usd > 0 ? (
              `+$${vm.settlement.settled_usd.toFixed(2)}`
            ) : (
              <span className="ax-glitch-live">$0 · WITHHELD</span>
            )}
          </span>
        )}
      </div>

      {/* Transient speech bubble near the node. */}
      {bubble && (
        <div
          className={`${styles.bubble} pointer-events-none absolute z-30 max-w-[180px] rounded-lg border border-hud-neutral bg-surface px-2.5 py-1.5 font-mono text-[9.5px] leading-snug text-fg-muted shadow-glow-emerald`}
          style={bubbleStyle(point, diameter)}
        >
          {renderMentions(bubble)}
        </div>
      )}

      {hover && <NodeHoverCard node={node} vm={vm} side={openSide} />}
    </div>
  );
}

/**
 * Render a floating-bubble line with @mentions tinted emerald — the same
 * "deterministic @mention routing" cue the WorkRoom transcript shows as chips,
 * kept lighter here (just colour) so it stays legible in the small bubble.
 */
function renderMentions(content: string) {
  return content.split(/(@[\w./-]+)/g).map((p, i) =>
    p.startsWith("@") ? (
      <span key={i} className="font-medium text-emerald-glow">
        {p}
      </span>
    ) : (
      <span key={i}>{p}</span>
    ),
  );
}

/* ── style helpers ─────────────────────────────────────────────────── */

function ringColor(status: NodeStatus, worst: string | null): string {
  if (worst === "unsupported") return "var(--ax-red)";
  if (worst === "partial") return "var(--ax-gold)";
  if (worst === "confirmed") return "var(--ax-emerald)";
  if (status === "paid") return "var(--ax-emerald)";
  if (status === "withheld") return "var(--ax-red)";
  if (status === "hired" || status === "working") return "var(--ax-emerald)";
  if (status === "bidding") return "rgb(var(--ax-border-neutral-rgb) / 0.3)";
  return "rgb(var(--ax-border-neutral-rgb) / 0.14)";
}

function glowFor(status: NodeStatus, worst: string | null): string {
  if (worst === "unsupported" || status === "withheld") return "var(--ax-glow-red)";
  if (worst === "partial") return "var(--ax-glow-gold)";
  return "var(--ax-glow-emerald)";
}

/** Place a stamp on the rim pointing toward the core (inward). */
function stampStyle(
  point: NodePoint,
  diameter: number,
  worst: string,
): React.CSSProperties {
  const vs = verdictStyle(worst as "confirmed" | "partial" | "unsupported");
  // Inward direction = toward center = opposite of the outward angle.
  const inwardX = -Math.cos(point.angle);
  const inwardY = -Math.sin(point.angle);
  const off = diameter * 0.42;
  const size = Math.round(diameter * 0.54);
  return {
    width: size,
    height: size,
    marginLeft: inwardX * off,
    marginTop: inwardY * off,
    color: vs.fg,
    borderColor: vs.fg,
    background: "rgb(var(--ax-canvas-rgb))",
    boxShadow: `0 0 10px -2px ${vs.fg}`,
  };
}

/** Place the price/settlement tag on the OUTWARD side of the node. */
function tagStyle(
  _point: NodePoint,
  diameter: number,
  _which: "price",
): React.CSSProperties {
  // Anchor the bid price tag ABOVE the disc (never angular-outward): the label
  // band always sits directly BELOW the disc, so an outward tag on a downward-
  // facing node (e.g. the bottom node) used to land on top of the handle. Above
  // the disc it can't collide with the label, on any node around the ring.
  const off = diameter * 0.5 + 9;
  return {
    left: "50%",
    top: "50%",
    transform: `translate(-50%, calc(-50% - ${off}px))`,
  };
}

/** Float the speech bubble outward from the node so it doesn't cover the disc. */
function bubbleStyle(point: NodePoint, diameter: number): React.CSSProperties {
  const outX = Math.cos(point.angle);
  const outY = Math.sin(point.angle);
  const off = diameter * 0.5 + 14;
  return {
    left: "50%",
    top: "50%",
    transform: `translate(calc(-50% + ${outX * off}px), calc(-50% + ${outY * off - 8}px))`,
  };
}
