"use client";

import {
  HudPanel,
  Eyebrow,
  CountUp,
  SegmentBar,
  Stars,
  Shield,
  Coin,
  Gavel,
  ArrowUpRight,
} from "@/components/hud";
import type { ReactNode } from "react";

function StatBlock({
  value,
  qualifier,
  label,
}: {
  value: ReactNode;
  qualifier: string;
  label: string;
}) {
  return (
    <div className="flex min-w-0 flex-col gap-1.5 rounded-md border border-hud-neutral bg-surface-2 p-3 sm:p-4">
      <span className="tnum block min-w-0 truncate font-mono text-[20px] font-medium leading-none text-emerald sm:text-[23px]">
        {value}
      </span>
      <span className="font-display text-[11px] font-bold uppercase tracking-[0.1em] text-fg">
        {label}
      </span>
      <span className="tnum font-mono text-[10.5px] leading-snug text-fg-faint">
        {qualifier}
      </span>
    </div>
  );
}

export function Numbers() {
  return (
    <section className="mx-auto max-w-6xl px-5 py-20 sm:px-8 sm:py-24">
      <div className="ax-fade-up mb-12 max-w-2xl">
        <Eyebrow live tone="emerald" className="mb-4">
          Measured · not claimed
        </Eyebrow>
        <h2 className="font-display text-[28px] font-bold leading-tight tracking-tight text-fg sm:text-[36px]">
          The numbers
        </h2>
        <p className="mt-4 font-mono text-[13px] leading-[1.8] text-fg-muted">
          Every figure below traces to a real evaluation or an on-chain
          settlement. No rounding away the sample size.
        </p>
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        {/* Headline: fabrications caught */}
        <HudPanel
          tone="emerald"
          eyebrow="ADVERSARIAL CATCH RATE"
          live
          title={
            <span className="flex items-center gap-2.5">
              <span className="text-emerald">
                <Shield size={17} />
              </span>
              FABRICATIONS CAUGHT
            </span>
          }
          className="lg:col-span-2"
        >
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <div className="flex min-w-0 flex-col justify-center">
              <span className="tnum font-display text-[52px] font-black leading-none text-emerald sm:text-[64px]">
                <CountUp value={100} suffix="%" />
              </span>
              <span className="tnum mt-2 font-mono text-[12px] text-fg-muted">
                81 / 81 LLM-fabricated false claims caught
              </span>
              <span className="font-mono text-[11px] text-fg-faint">
                Adversary: contract-audit verifier
              </span>
              <div className="mt-4 max-w-[260px]">
                <SegmentBar value={1} tone="emerald" />
              </div>
            </div>
            <div className="grid min-w-0 grid-cols-1 gap-3">
              <StatBlock
                value={<CountUp value={2.5} decimals={1} suffix="%" />}
                label="False-withhold"
                qualifier="real work wrongly held back"
              />
              <StatBlock
                value={<CountUp value={97.6} decimals={1} suffix="%" />}
                label="Precision"
                qualifier="paid claims that are real"
              />
              <StatBlock
                value={<CountUp value={0.015} decimals={3} />}
                label="Calibration ECE"
                qualifier="lower is better-calibrated"
              />
            </div>
          </div>
        </HudPanel>

        {/* On-chain settlement */}
        <HudPanel
          tone="gold"
          eyebrow="ON-CHAIN · TESTNET"
          title={
            <span className="flex items-center gap-2.5">
              <span className="text-gold">
                <Coin size={17} />
              </span>
              REAL USDC SETTLEMENT
            </span>
          }
        >
          <div className="flex flex-col gap-3">
            <p className="font-mono text-[12px] leading-[1.7] text-fg-muted">
              Live x402 payments on{" "}
              <span className="text-gold">Base Sepolia (testnet)</span>.
            </p>
            <div className="flex flex-col gap-2">
              <Row k="Verified transactions" v="2 on Basescan" />
              <Row k="Pay fraction" v="0.75" />
              <Row k="Settlement" v="per verified claim" />
            </div>
            <span className="mt-1 inline-flex w-fit items-center gap-1.5 rounded-[4px] border border-gold/40 bg-gold-dim px-2 py-1 font-mono text-[10px] uppercase tracking-[0.1em] text-gold">
              <ArrowUpRight size={12} />
              Testnet
            </span>
          </div>
        </HudPanel>

        {/* NDA job type */}
        <HudPanel
          tone="emerald"
          eyebrow="JOB TYPE · NDA AUDIT"
          title="NDA RESULTS"
        >
          <div className="grid grid-cols-3 gap-2.5">
            <StatBlock
              value={<CountUp value={10} />}
              label="of 10"
              qualifier="caught"
            />
            <StatBlock
              value={<CountUp value={0} suffix="%" />}
              label="False-withhold"
              qualifier="none held back"
            />
            <StatBlock
              value={<CountUp value={0.009} decimals={3} />}
              label="ECE"
              qualifier="calibration"
            />
          </div>
        </HudPanel>

        {/* Reputation flywheel */}
        <HudPanel
          tone="default"
          eyebrow="REPUTATION FLYWHEEL"
          title={
            <span className="flex items-center gap-2.5">
              <span className="text-emerald">
                <Gavel size={17} />
              </span>
              HONESTY COMPOUNDS
            </span>
          }
          className="lg:col-span-2"
        >
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <div className="flex flex-col gap-2 rounded-md border border-hud bg-surface-2 p-4">
              <span className="font-display text-[11px] font-bold uppercase tracking-[0.1em] text-emerald">
                Honest agent
              </span>
              <div className="flex items-center gap-3">
                <Stars value={0.8} size={14} />
                <span className="tnum font-mono text-[12px] text-fg-muted">
                  0.5 &rarr; 0.8
                </span>
              </div>
              <SegmentBar value={0.8} tone="emerald" />
              <span className="tnum font-mono text-[11px] text-fg-faint">
                Hired ~99% of the time
              </span>
            </div>
            <div className="flex flex-col gap-2 rounded-md border border-danger/40 bg-surface-2 p-4">
              <span className="font-display text-[11px] font-bold uppercase tracking-[0.1em] text-danger">
                Liar
              </span>
              <div className="flex items-center gap-3">
                <Stars value={0.2} size={14} />
                <span className="tnum font-mono text-[12px] text-fg-muted">
                  0.5 &rarr; 0.2
                </span>
              </div>
              <SegmentBar value={0.2} tone="red" />
              <span className="tnum font-mono text-[11px] text-fg-faint">
                Collapses — stops getting hired
              </span>
            </div>
          </div>
        </HudPanel>
      </div>
    </section>
  );
}

function Row({ k, v }: { k: string; v: string }) {
  return (
    <div className="flex items-baseline justify-between gap-3 border-b border-hud-neutral pb-1.5">
      <span className="font-mono text-[11px] uppercase tracking-[0.08em] text-fg-faint">
        {k}
      </span>
      <span className="tnum font-mono text-[12px] text-fg">{v}</span>
    </div>
  );
}
