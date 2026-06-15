"use client";

import { ProviderLogo } from "@/components/ProviderLogo";
import { Stars, SegmentBar, VerdictGlyph } from "@/components/hud";
import { verdictStyle, usd } from "@/lib/ui";
import { GATEWAYS, FRAMEWORKS } from "@/lib/providers";
import type { ArenaNode } from "./geometry";
import type { NodeVM } from "./selectors";
import styles from "./arena.module.css";

/**
 * Rich on-hover detail card for a node — this is where the "tooltip-only" data
 * lives: label, model + provider + gateway (with logo), owner / cross-owner,
 * reputation, the node's bid (price + relevance), the verdicts it earned, and
 * its settled amount + tx link. Positioned by the parent; it renders inward so
 * it never clips off-canvas.
 */
export function NodeHoverCard({
  node,
  vm,
  side,
}: {
  node: ArenaNode;
  vm: NodeVM;
  /** Which side of the node to open toward (keeps it on-canvas). */
  side: "left" | "right";
}) {
  const p = node.provider;
  const bid = vm.bid;
  const s = vm.settlement;

  return (
    <div
      className={`${styles.card} pointer-events-none absolute top-1/2 z-40 w-[224px] -translate-y-1/2 rounded-lg border border-hud-neutral bg-surface p-3 text-left shadow-glow-emerald`}
      style={
        side === "right"
          ? { left: "calc(100% + 10px)" }
          : { right: "calc(100% + 10px)" }
      }
    >
      {/* Header — logo + label + handle */}
      <div className="flex items-center gap-2">
        <ProviderLogo provider={p} size={22} />
        <div className="min-w-0">
          <div className="truncate font-display text-[12px] font-bold text-fg">
            {node.label}
          </div>
          <div className="truncate font-mono text-[10px] text-fg-muted">
            {node.handle}
          </div>
        </div>
      </div>

      {/* Model · provider · gateway */}
      <dl className="mt-2.5 space-y-1 font-mono text-[10px]">
        <Row label="model" value={p.model} />
        <Row label="provider" value={p.providerLabel} />
        <Row label="gateway" value={GATEWAYS[p.gateway].label} />
        {/* Agent framework — orthogonal to the model provider above. Non-native
            frameworks get the framework accent so the cross-framework collab
            reads at a glance; native stays muted. */}
        <Row
          label="framework"
          value={
            vm.framework === "native" ? (
              <span className="text-fg-muted">native</span>
            ) : (
              <span
                title="a different agent framework collaborating via Band"
                style={{ color: FRAMEWORKS[vm.framework].accent ?? undefined }}
              >
                {FRAMEWORKS[vm.framework].label} · via Band
              </span>
            )
          }
        />
        <Row
          label="owner"
          value={
            node.crossOwner ? (
              <span className="text-gold">{node.owner ?? "external"} · cross-owner</span>
            ) : (
              <span className="text-fg-muted">{node.owner ?? "you"}</span>
            )
          }
        />
      </dl>

      {/* Reputation + bid */}
      {bid && (
        <div className="mt-2.5 border-t border-hud-neutral pt-2">
          <div className="flex items-center justify-between font-mono text-[10px] text-fg-muted">
            <span>reputation</span>
            <Stars value={bid.reputation} size={11} />
          </div>
          {/* Buyer-facing confidence badge — Formula 1: ≥385 jobs for ±5% CI. */}
          {bid.n_jobs < 385 ? (
            <div
              className="mt-1 flex items-center gap-1 font-mono text-[9px]"
              title={`needs ~385 jobs for ±5% confidence · ${bid.n_jobs} so far`}
            >
              <span
                className="rounded-sm px-1 py-0.5 font-bold"
                style={{
                  color: "var(--ax-gold)",
                  background: "rgb(var(--ax-gold-rgb,255,194,51) / 0.10)",
                  border: "1px solid rgb(var(--ax-gold-rgb,255,194,51) / 0.30)",
                }}
              >
                low confidence
              </span>
              <span className="text-fg-faint">
                {bid.n_jobs} job{bid.n_jobs !== 1 ? "s" : ""} · needs ~385
              </span>
            </div>
          ) : (
            <div className="mt-1 font-mono text-[9px] text-fg-faint">
              {bid.n_jobs} jobs · ±5% confident
            </div>
          )}
          <div className="mt-1 flex items-center justify-between font-mono text-[10px]">
            <span className="text-fg-muted">bid</span>
            <span className="tabular-nums text-gold">{usd(bid.price_usd)}</span>
          </div>
          <div className="mt-1 flex items-center gap-2 font-mono text-[10px] text-fg-muted">
            <span className="shrink-0">relevance</span>
            <SegmentBar value={bid.relevance} tone="emerald" segments={10} />
            <span className="shrink-0 tabular-nums text-fg-faint">
              {(bid.relevance * 100).toFixed(0)}%
            </span>
          </div>
        </div>
      )}

      {/* Verdicts earned */}
      {vm.findings.length > 0 && (
        <div className="mt-2.5 border-t border-hud-neutral pt-2">
          <div className="mb-1 font-mono text-[9px] uppercase tracking-[0.16em] text-fg-faint">
            verdicts
          </div>
          <ul className="space-y-1">
            {vm.findings.map((f, i) => {
              const fv = verdictStyle(f.verdict);
              return (
                <li
                  key={i}
                  className="flex items-center gap-1.5 font-mono text-[10px]"
                  style={{ color: fv.fg }}
                >
                  <VerdictGlyph glyph={fv.glyph} size={12} />
                  <span className="tabular-nums">§{f.clause_ref}</span>
                  <span className="opacity-90">
                    {fv.label === "Fake" ? "fabricated" : fv.label.toLowerCase()}
                  </span>
                </li>
              );
            })}
          </ul>
        </div>
      )}

      {/* Behavioral drift — only shown when a signal is present. A flagged
          signal uses the danger accent (cheating caught); a clean one stays
          muted ("behaving in-baseline"). */}
      {vm.drift && (
        <div className="mt-2.5 border-t border-hud-neutral pt-2 font-mono text-[10px]">
          <div className="mb-1 flex items-center justify-between">
            <span className="uppercase tracking-[0.16em] text-fg-faint text-[9px]">
              behavioral drift
            </span>
            <span
              className="rounded-sm px-1 py-0.5 text-[9px] font-bold uppercase"
              style={
                vm.drift.flagged
                  ? {
                      color: "var(--ax-red)",
                      borderWidth: 1,
                      borderColor: "var(--ax-red)",
                      background: "rgb(var(--ax-canvas-rgb))",
                    }
                  : { color: "var(--ax-emerald-glow)" }
              }
            >
              {vm.drift.severity}
            </span>
          </div>
          <div
            className="leading-snug"
            style={{ color: vm.drift.flagged ? "var(--ax-red)" : "var(--ax-fg-muted, inherit)" }}
          >
            {vm.drift.summary}
          </div>
          <dl className="mt-1.5 space-y-1">
            <Row label="ran model" value={vm.drift.model} />
            <Row label="baseline" value={vm.drift.baseline_label} />
            {vm.drift.overcharge_ratio != null && (
              <Row
                label="overcharge"
                value={
                  <span style={{ color: "var(--ax-red)" }} className="tabular-nums">
                    {vm.drift.overcharge_ratio.toFixed(1)}×
                  </span>
                }
              />
            )}
          </dl>
        </div>
      )}

      {/* Settlement */}
      {s && (
        <div className="mt-2.5 border-t border-hud-neutral pt-2 font-mono text-[10px]">
          <div className="flex items-center justify-between">
            <span className="text-fg-muted">settled</span>
            <span
              className="tabular-nums"
              style={{ color: s.settled_usd > 0 ? "var(--ax-emerald-glow)" : "var(--ax-red)" }}
            >
              {s.settled_usd > 0 ? `+${usd(s.settled_usd)}` : "$0 · WITHHELD"}
            </span>
          </div>
          {s.tx_hash ? (
            <a
              href={`https://sepolia.basescan.org/tx/${s.tx_hash}`}
              target="_blank"
              rel="noreferrer"
              className="pointer-events-auto mt-1 block truncate text-[9px] text-emerald-glow underline decoration-dotted"
            >
              {s.tx_hash.slice(0, 14)}… · x402
            </a>
          ) : (
            <div className="mt-1 truncate text-[9px] text-fg-faint">{s.status}</div>
          )}
        </div>
      )}
    </div>
  );
}

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-3">
      <dt className="text-fg-faint">{label}</dt>
      <dd className="truncate text-right text-fg">{value}</dd>
    </div>
  );
}
