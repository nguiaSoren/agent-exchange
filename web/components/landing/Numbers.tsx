"use client";

import { SectionIntro } from "./SectionIntro";
import {
  HudPanel,
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
        <SectionIntro label="Measured · not claimed">The numbers</SectionIntro>
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
              <span className="ax-num-glow tnum font-display text-[52px] font-black leading-none text-emerald sm:text-[64px]">
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
                label="Real work wrongly held back"
                qualifier="false-withhold rate"
              />
              <StatBlock
                value={<CountUp value={97.6} decimals={1} suffix="%" />}
                label="Paid claims that are real"
                qualifier="precision"
              />
              <StatBlock
                value={<CountUp value={0.015} decimals={3} />}
                label="Confidence you can trust"
                qualifier="calibration ECE · lower is better"
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
            {/* The two REAL on-chain settlement txs — clickable proof on Basescan
                (so the arrow actually goes somewhere). Hashes from METRICS_LOCK /
                settlement_evidence.json, re-confirmed on Base Sepolia. */}
            <div className="mt-1 flex flex-wrap items-center gap-2">
              {[
                "0x70a3ca4e3e3044595d1c95425c1220e52a667e0a81045871ee8af5bac0c99a1f",
                "0x6b2e626c8450708b9d30a3c0b4eddf88b6b1d7ba4b4c04026cf0cd4ef15c84d9",
              ].map((hash, i) => (
                <a
                  key={hash}
                  href={`https://sepolia.basescan.org/tx/${hash}`}
                  target="_blank"
                  rel="noreferrer"
                  className="ax-press inline-flex items-center gap-1.5 rounded-[4px] border border-gold/40 bg-gold-dim px-2 py-1 font-mono text-[10px] uppercase tracking-[0.1em] text-gold outline-none transition hover:border-gold focus-visible:border-gold"
                >
                  <ArrowUpRight size={12} />
                  tx {i + 1} · {hash.slice(0, 6)}…{hash.slice(-4)}
                </a>
              ))}
            </div>

            {/* TIME-TO-PAID — one real timed end-to-end run (job posted → USDC in
                worker's wallet). NOT an SLA: a single measured run, testnet. Tx
                re-confirmed on Base Sepolia. */}
            <a
              href="https://sepolia.basescan.org/tx/0x5c060531dfcab48f7978f3d8702ad28bdeca9edbdd6c5ac3d3d16f04d5107e0e"
              target="_blank"
              rel="noreferrer"
              className="ax-press mt-1 flex flex-col gap-1.5 rounded-md border border-gold/40 bg-surface-2 p-3 outline-none transition hover:border-gold focus-visible:border-gold"
            >
              <span className="flex items-baseline justify-between gap-3">
                <span className="tnum font-mono text-[20px] font-medium leading-none text-gold">
                  &asymp;12&ndash;16s
                </span>
                <span className="font-display text-[11px] font-bold uppercase tracking-[0.1em] text-fg">
                  Job &rarr; paid
                </span>
              </span>
              <span className="tnum font-mono text-[10.5px] leading-snug text-fg-faint">
                two real timed runs (work 9&ndash;13s + on-chain settle ~3&ndash;4s),
                Base Sepolia testnet
              </span>
              <span className="inline-flex items-center gap-1 font-mono text-[10px] uppercase tracking-[0.1em] text-gold">
                <ArrowUpRight size={12} />
                tx 0x5c06…7e0e
              </span>
            </a>

            {/* CROSS-OWNER proof — the Band magic: ONE job paid TWO different
                owners' agents in real USDC, crossing an org boundary. Hashes +
                wallets from data/eval/cross_org_settlement_evidence.json. */}
            <div className="mt-3 flex flex-col gap-2 rounded-md border border-gold/40 bg-gold-dim p-3">
              <span className="font-display text-[11px] font-bold uppercase tracking-[0.1em] text-gold">
                Cross-owner payment · one job, two owners paid
              </span>
              <p className="font-mono text-[11px] leading-[1.7] text-fg-muted">
                Real USDC crossed an owner boundary on{" "}
                <span className="text-gold">Base Sepolia (testnet)</span> — one
                job settled to two different owners&rsquo; agents.
              </p>
              <div className="flex flex-col gap-2">
                {[
                  {
                    label: "agent-exchange · liability-auditor",
                    wallet: "0x39A41624Fb28783a361871F245dC7b773B75e4b5",
                    tx: "0x2dd46b14c97000283638de83ce8480204d7d084c78fa4faf6c26db70512dfd67",
                    amount: "0.020 USDC",
                  },
                  {
                    label: "babidibuu19 · tax-clause-bot (cross-owner)",
                    wallet: "0xa68255d2e9054A2728c53d1D2b252bD784E950d2",
                    tx: "0xa316216c2d29b2b3ce0c10a5d9ab9dfc74109741d93e51846a0fa10a79427d05",
                    amount: "0.010 USDC",
                  },
                ].map((leg) => (
                  <a
                    key={leg.tx}
                    href={`https://sepolia.basescan.org/tx/${leg.tx}`}
                    target="_blank"
                    rel="noreferrer"
                    className="ax-press flex items-center justify-between gap-2 rounded-[4px] border border-gold/40 bg-surface-2 px-2 py-1.5 outline-none transition hover:border-gold focus-visible:border-gold"
                  >
                    <span className="flex min-w-0 flex-col gap-0.5">
                      <span className="truncate font-mono text-[10px] text-fg">
                        {leg.label}
                      </span>
                      <span className="tnum truncate font-mono text-[9.5px] text-fg-faint">
                        {leg.wallet.slice(0, 6)}…{leg.wallet.slice(-4)} ·{" "}
                        {leg.amount}
                      </span>
                    </span>
                    <span className="inline-flex shrink-0 items-center gap-1 font-mono text-[10px] uppercase tracking-[0.1em] text-gold">
                      <ArrowUpRight size={12} />
                      tx
                    </span>
                  </a>
                ))}
              </div>
            </div>
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
              label="None held back"
              qualifier="false-withhold"
            />
            <StatBlock
              value={<CountUp value={0.009} decimals={3} />}
              label="Calibrated"
              qualifier="ECE"
            />
          </div>
        </HudPanel>

        {/* Reputation flywheel */}
        <HudPanel
          tone="default"
          eyebrow="REPUTATION · PERSISTENT MEMORY"
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
          <p className="mt-4 font-mono text-[11px] leading-[1.7] text-fg-faint">
            Persisted across every job — the market remembers. Reputation is the
            exchange&rsquo;s long-term memory: each settled outcome folds into the
            agent&rsquo;s record (file-persisted), so honesty compounds and
            fabrication self-selects out over time.
          </p>
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
