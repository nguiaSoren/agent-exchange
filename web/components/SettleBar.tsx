"use client";

import type { DoneEvent, SettleEvent } from "@/lib/events";
import { settledTotals } from "@/lib/runState";
import { prettyWorker, usd } from "@/lib/ui";
import { Avatar } from "./Avatar";
import {
  HudPanel,
  Eyebrow,
  CountUp,
  SegmentBar,
  CoinFlight,
  ArrowRight,
  ArrowUpRight,
  Check,
  Coin,
  Cross,
} from "@/components/hud";

const BASESCAN = "https://sepolia.basescan.org/tx/";

interface SettleBarProps {
  settlements: SettleEvent[];
  done: DoneEvent | null;
}

export function SettleBar({ settlements, done }: SettleBarProps) {
  const { settled, withheld } = settledTotals(settlements);

  return (
    <HudPanel
      eyebrow="SETTLEMENT · USDC via x402"
      live={settlements.length > 0}
      tone="gold"
      padded={false}
      title={
        <span className="flex items-center gap-2.5">
          <span className="text-gold">
            <Coin size={18} />
          </span>
          SETTLEMENT
        </span>
      }
      right={
        settlements.length > 0 ? (
          <div className="flex items-center gap-2">
            <span
              className="tnum inline-flex items-center gap-1.5 rounded-md px-2 py-1 font-mono text-[12px] font-medium"
              style={{
                background: "rgba(0,214,122,0.18)",
                color: "#2bff9a",
                boxShadow: "inset 0 0 0 1px rgba(0,214,122,0.55)",
              }}
            >
              <Check size={13} />
              {usd(settled)}
            </span>
            <span
              className="tnum inline-flex items-center gap-1.5 rounded-md px-2 py-1 font-mono text-[12px] font-medium"
              style={{
                background: "rgba(255,59,92,0.18)",
                color: "#ff3b5c",
                boxShadow: "inset 0 0 0 1px rgba(255,59,92,0.55)",
              }}
            >
              <Cross size={13} />
              {usd(withheld)}
            </span>
          </div>
        ) : undefined
      }
    >
      <div className="ax-scroll flex gap-4 overflow-x-auto px-5 py-5">
        {settlements.length === 0 && (
          <div className="flex h-28 w-full items-center justify-center px-8 text-center font-mono text-[12px] leading-relaxed text-fg-faint">
            Payments stream here once the verifier rules on each finding —
            verified work moves money, fabricated work settles at $0.
          </div>
        )}
        {settlements.map((s, i) => (
          <SettleCard key={`${s.worker}-${i}`} s={s} index={i} />
        ))}
      </div>

      {done && <DoneBanner done={done} />}
    </HudPanel>
  );
}

function SettleCard({ s, index }: { s: SettleEvent; index: number }) {
  const paid = s.settled_usd > 0;
  const fraction = s.authorized_usd > 0 ? s.settled_usd / s.authorized_usd : 0;
  const partial = paid && fraction < 0.999;
  const tone = paid ? (partial ? "gold" : "emerald") : "red";

  return (
    <article
      className={`ax-stagger ax-card ${
        paid ? (partial ? "ax-card-gold" : "") : "ax-card-red"
      } relative min-w-[244px] shrink-0 overflow-hidden rounded-lg border bg-surface-2 p-4`}
      style={{
        // @ts-expect-error CSS custom prop for stagger delay
        "--index": index,
        borderColor: paid
          ? partial
            ? "rgba(255,194,51,0.4)"
            : "rgba(0,214,122,0.4)"
          : "#ff3b5c",
        boxShadow: paid
          ? "none"
          : "0 0 0 1px rgba(255,59,92,0.4)",
      }}
    >
      {/* client → worker, with a gold coin in flight only when paid */}
      <div className="relative flex items-center justify-between">
        <div className="relative flex items-center gap-2 font-mono text-[10px] uppercase tracking-[0.1em] text-fg-faint">
          <span>client</span>
          <ArrowRight size={12} />
          <Avatar seed={s.worker} size={26} ring={paid} />
          {/* the coin flies from the "client" label across to the worker avatar.
              keyed by index so each settle event remounts + re-fires it. */}
          {paid && (
            <CoinFlight
              key={`coin-${index}`}
              dx={88}
              dy={0}
              size={15}
              delay={index * 60}
              className="left-0 top-1/2 -translate-y-1/2"
            />
          )}
        </div>
        {paid ? (
          <span
            className="tnum font-display text-[15px] font-bold text-emerald-glow"
            style={{ textShadow: "0 0 10px rgba(0,214,122,0.5)" }}
          >
            {usd(s.settled_usd)}
          </span>
        ) : (
          <span
            className="ax-glitch-live rounded-[4px] px-2 py-0.5 font-display text-[10px] font-bold uppercase tracking-[0.12em]"
            style={{
              background: "rgba(255,59,92,0.18)",
              color: "#ff3b5c",
              boxShadow: "inset 0 0 0 1px #ff3b5c",
            }}
          >
            $0 · Withheld
          </span>
        )}
      </div>

      <div className="relative mt-3">
        <div className="text-[13px] font-semibold text-fg">
          {prettyWorker(s.worker)}
        </div>
        <div className="tnum mt-0.5 font-mono text-[10.5px] text-fg-muted">
          {usd(s.settled_usd)} / {usd(s.authorized_usd)} authorized
        </div>
      </div>

      {/* pay fraction */}
      <div className="relative mt-3">
        <SegmentBar value={paid ? fraction : 0} tone={tone} variant="smooth" />
      </div>

      <div className="relative mt-3 flex items-center justify-between gap-2">
        <span
          className="truncate font-mono text-[10px]"
          style={{ color: paid ? "#7e9d90" : "#ff3b5c" }}
          title={s.status}
        >
          {s.status}
        </span>
        {s.tx_hash ? (
          <a
            href={`${BASESCAN}${s.tx_hash}`}
            target="_blank"
            rel="noopener noreferrer"
            className="ax-press flex shrink-0 items-center gap-1 rounded-[4px] border border-hud-neutral bg-canvas px-1.5 py-0.5 font-mono text-[10px] text-fg-muted hover:border-hud hover:text-emerald-glow"
          >
            <span className="tnum">tx</span>
            <ArrowUpRight size={11} />
          </a>
        ) : (
          <span className="shrink-0 font-mono text-[10px] text-fg-faint">
            no tx
          </span>
        )}
      </div>
    </article>
  );
}

function DoneBanner({ done }: { done: DoneEvent }) {
  const ok = done.gate_passed;
  return (
    <div
      className="ax-fade-up flex flex-wrap items-center gap-x-8 gap-y-4 border-t border-hud-neutral px-5 py-5"
      style={{
        background: ok ? "rgba(0,214,122,0.06)" : "rgba(255,59,92,0.06)",
      }}
    >
      <span
        className="flex h-10 w-10 shrink-0 items-center justify-center rounded-md"
        style={{
          background: ok ? "rgba(0,214,122,0.18)" : "rgba(255,59,92,0.18)",
          color: ok ? "#2bff9a" : "#ff3b5c",
          boxShadow: `inset 0 0 0 1px ${ok ? "rgba(0,214,122,0.55)" : "rgba(255,59,92,0.55)"}`,
        }}
      >
        {ok ? <Check size={20} /> : <Cross size={20} />}
      </span>

      <div className="flex flex-col gap-1">
        <Eyebrow tone={ok ? "emerald" : "red"}>
          {ok ? "GATE PASSED" : "GATE FAILED"}
        </Eyebrow>
        <span className="tnum font-mono text-[11px] text-fg-faint">
          pay fraction {(done.pay_fraction * 100).toFixed(0)}%
        </span>
      </div>

      {/* pay-fraction bar */}
      <div className="min-w-[160px] flex-1 basis-[180px]">
        <SegmentBar
          value={done.pay_fraction}
          tone={ok ? "emerald" : "red"}
          variant="segmented"
        />
      </div>

      <div className="flex items-baseline gap-2">
        <span className="font-mono text-[10px] uppercase tracking-[0.1em] text-fg-faint">
          settled
        </span>
        <span className="tnum font-display text-[18px] font-bold text-emerald-glow">
          <CountUp value={done.total_settled_usd} prefix="$" decimals={2} />
        </span>
      </div>

      <div className="flex items-baseline gap-2">
        <span className="font-mono text-[10px] uppercase tracking-[0.1em] text-fg-faint">
          withheld
        </span>
        <span className="tnum font-display text-[18px] font-bold text-danger">
          <CountUp value={done.total_withheld_usd} prefix="$" decimals={2} />
        </span>
      </div>

      <p className="w-full text-[12.5px] leading-relaxed text-fg-muted">
        {done.catch_summary}
      </p>
    </div>
  );
}
