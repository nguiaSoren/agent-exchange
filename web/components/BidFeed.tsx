"use client";

import type { BidEvent, HireEvent, PoolAgent } from "@/lib/events";
import { prettyWorker, usd } from "@/lib/ui";
import { Avatar } from "./Avatar";
import {
  HudPanel,
  Eyebrow,
  SegmentBar,
  Stars,
  Exchange,
  Check,
  Coin,
  Robot,
} from "@/components/hud";

interface BidFeedProps {
  pool: PoolAgent[];
  bids: BidEvent[];
  hire: HireEvent | null;
  hiredWorkers: Set<string>;
}

/**
 * Maps a worker id (carried on bids/hires, e.g. "data_privacy") to its pool
 * agent. Pool ids/handles are descriptive; we match on a normalized token.
 */
function poolForWorker(pool: PoolAgent[], worker: string): PoolAgent | undefined {
  const w = worker.toLowerCase().replace(/[^a-z]/g, "");
  return pool.find((p) => {
    const hay = `${p.id} ${p.handle} ${p.name}`.toLowerCase().replace(/[^a-z]/g, "");
    return hay.includes(w) || w.includes(p.id.toLowerCase().replace(/[^a-z]/g, ""));
  });
}

export function BidFeed({ pool, bids, hire, hiredWorkers }: BidFeedProps) {
  const declined = new Set(hire?.declined ?? []);
  const hiredCount = bids.filter((b) => hiredWorkers.has(b.worker)).length;

  return (
    <HudPanel
      eyebrow="MARKETPLACE · OPEN BIDS"
      live={bids.length > 0}
      tone="emerald"
      padded={false}
      title={
        <span className="flex items-center gap-2.5">
          <span className="text-emerald-glow">
            <Robot size={17} />
          </span>
          MARKET
        </span>
      }
      right={
        <div className="flex items-center gap-2">
          {hiredCount > 0 && (
            <span
              className="tnum inline-flex items-center gap-1 rounded-md px-2 py-1 font-mono text-[11px] font-medium"
              style={{
                background: "rgba(0,214,122,0.18)",
                color: "#2bff9a",
                boxShadow: "inset 0 0 0 1px rgba(0,214,122,0.4)",
              }}
            >
              <Check size={12} />
              {hiredCount} hired
            </span>
          )}
          <span className="tnum font-mono text-[11px] text-fg-faint">
            {bids.length} bid{bids.length === 1 ? "" : "s"} · {pool.length} pool
          </span>
        </div>
      }
    >
      <div className="ax-scroll max-h-[440px] space-y-2.5 overflow-y-auto px-4 py-4">
        {pool.length === 0 && bids.length === 0 && (
          <Empty text="Agents appear here as the pool is discovered." />
        )}

        {bids.map((bid, i) => {
          const agent = poolForWorker(pool, bid.worker);
          const hired = hiredWorkers.has(bid.worker);
          const isDeclined = declined.has(bid.worker);
          const crossOwner = agent?.cross_owner ?? false;
          const seed = agent?.handle ?? bid.worker;

          return (
            <article
              key={`${bid.worker}-${i}`}
              className={`ax-stagger relative overflow-hidden rounded-lg border bg-surface-2 p-3.5 transition-all duration-300 ${
                hired ? "ax-card" : ""
              }`}
              style={{
                // @ts-expect-error CSS custom prop for stagger delay
                "--index": i,
                borderColor: hired
                  ? "#00d67a"
                  : isDeclined
                    ? "rgba(255,255,255,0.06)"
                    : "rgba(0,214,122,0.18)",
                boxShadow: hired
                  ? "0 0 0 1px #00d67a, 0 0 18px -6px #00d67a"
                  : "none",
                opacity: isDeclined ? 0.5 : 1,
              }}
            >
              <div className="flex items-start gap-3">
                <Avatar seed={seed} label={agent?.name ?? bid.worker} ring={hired} />
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="truncate font-display text-[12.5px] font-bold uppercase tracking-[0.04em] text-fg">
                      {agent?.name ?? prettyWorker(bid.worker)}
                    </span>
                    {hired && (
                      <span
                        className="inline-flex items-center gap-1 rounded-[4px] px-1.5 py-0.5 font-mono text-[9px] font-medium uppercase tracking-[0.1em]"
                        style={{
                          background: "rgba(0,214,122,0.18)",
                          color: "#2bff9a",
                          boxShadow: "inset 0 0 0 1px #00d67a",
                        }}
                      >
                        <Check size={10} />
                        Hired
                      </span>
                    )}
                    {isDeclined && (
                      <span className="rounded-[4px] border border-hud-neutral bg-canvas px-1.5 py-0.5 font-mono text-[9px] font-medium uppercase tracking-[0.1em] text-fg-faint">
                        Passed
                      </span>
                    )}
                  </div>
                  <div className="truncate font-mono text-[11px] text-fg-muted">
                    {agent?.handle ?? `@${bid.worker}`}
                  </div>

                  {crossOwner && (
                    <div
                      className="mt-2 inline-flex items-center gap-1.5 rounded-[4px] px-1.5 py-0.5 font-mono text-[10px] font-medium uppercase tracking-[0.08em]"
                      style={{
                        background: "rgba(255,194,51,0.16)",
                        color: "#ffc233",
                        boxShadow: "inset 0 0 0 1px rgba(255,194,51,0.45)",
                      }}
                    >
                      <Exchange size={11} /> cross-owner agent
                    </div>
                  )}

                  <div className="mt-2.5 flex items-center justify-between gap-2">
                    <Stars value={bid.reputation} />
                    <span
                      className="tnum inline-flex items-center gap-1 font-display text-[14px] font-bold"
                      style={{ color: "#ffc233" }}
                    >
                      <Coin size={13} />
                      {usd(bid.price_usd)}
                    </span>
                  </div>

                  {/* relevance probe */}
                  <div className="mt-2.5">
                    <div className="mb-1 flex items-center justify-between font-mono text-[10px] uppercase tracking-[0.1em] text-fg-faint">
                      <span>relevance</span>
                      <span className="tnum">
                        {(bid.relevance * 100).toFixed(0)}%
                      </span>
                    </div>
                    <SegmentBar
                      value={bid.relevance}
                      tone="emerald"
                      variant="segmented"
                    />
                  </div>
                </div>
              </div>
            </article>
          );
        })}
      </div>

      {hire && (
        <div className="border-t border-hud-neutral px-5 py-3 font-mono text-[11px] leading-relaxed text-fg-muted">
          <Eyebrow tone="emerald">Hiring policy</Eyebrow>
          <p className="mt-1.5 text-fg-muted">
            {hire.strategy}
            <span className="tnum ml-1 text-fg-faint">
              (target pay fraction {(hire.pay_fraction_target * 100).toFixed(0)}%)
            </span>
          </p>
        </div>
      )}
    </HudPanel>
  );
}

function Empty({ text }: { text: string }) {
  return (
    <div className="flex h-full min-h-[140px] items-center justify-center px-6 text-center font-mono text-[12px] text-fg-faint">
      {text}
    </div>
  );
}
