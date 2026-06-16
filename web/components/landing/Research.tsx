"use client";

import { Eyebrow, CountUp, Shield } from "@/components/hud";
import { SectionIntro } from "./SectionIntro";
import type { ReactNode } from "react";

/**
 * Research — the "proof" section. Presents the calibrated verifier's REAL
 * measured metrics (the moat): adversarial catch-rate, false-withhold,
 * precision, and calibration (ECE) — for BOTH job types — plus a
 * dependency-free inline-SVG reliability curve. Every number traces to a
 * file in the repo and shows its sample size; nothing is rounded up or
 * invented. (Sources: data/eval/catch_rate_report.json [contract-audit,
 * N=162], data/eval/nda_catch_rate_report.json [NDA, N=22], and
 * ../METRICS_LOCK.md — the locked headline.)
 */

// ── Measured data, read verbatim from the repo (do not edit casually) ────────
// Contract-audit: data/eval/catch_rate_report.json
const CONTRACT = {
  n: 162,
  fabricated: 81,
  genuine: 81,
  caught: 81, // tp
  falseWithheld: 2, // fp
  catchRatePct: 100, // 81/81
  falseWithholdPct: 2.5, // 2/81 = 0.0247
  precisionPct: 97.6, // 81/83
  ece: 0.015, // 0.0148...
  // reliability bins (lo,hi,count,mean_confidence,accuracy) — only populated bins
  bins: [
    { conf: 0.7, acc: 1.0, count: 1 },
    { conf: 0.8, acc: 1.0, count: 2 },
    { conf: 0.998, acc: 0.987, count: 159 },
  ],
};
// NDA: data/eval/nda_catch_rate_report.json
const NDA = {
  n: 22,
  fabricated: 10,
  genuine: 12,
  caught: 10,
  falseWithheld: 0,
  catchRatePct: 100, // 10/10
  falseWithholdPct: 0, // 0/12
  precisionPct: 100, // 10/10
  ece: 0.005, // 0.00454...
  bins: [{ conf: 0.995, acc: 1.0, count: 22 }],
};

// ── Big-numeral metric callout ───────────────────────────────────────────────
function Metric({
  value,
  label,
  fraction,
  plain,
  tone = "fg",
}: {
  value: ReactNode;
  label: string;
  fraction: string;
  plain: string;
  tone?: "fg" | "emerald" | "gold";
}) {
  const valueColor =
    tone === "emerald"
      ? "text-emerald ax-num-glow"
      : tone === "gold"
        ? "text-gold ax-num-glow-gold"
        : "text-fg";
  return (
    <div className="flex flex-col gap-2 border-t border-hud-neutral pt-4">
      <span
        className={`tnum font-display text-[40px] font-black leading-none sm:text-[48px] ${valueColor}`}
      >
        {value}
      </span>
      <span className="font-display text-[11px] font-bold uppercase tracking-[0.14em] text-fg">
        {label}
      </span>
      <span className="tnum font-mono text-[11px] leading-snug text-fg-faint">
        {fraction}
      </span>
      <span className="font-mono text-[11.5px] leading-[1.65] text-fg-muted">
        {plain}
      </span>
    </div>
  );
}

// ── Reliability / calibration curve (pure inline SVG, no chart library) ──────
// x = predicted confidence, y = observed accuracy. The diagonal is perfect
// calibration; points are the measured per-bin (mean_confidence, accuracy),
// sized by how many claims fell in that bin. Points hugging the diagonal =
// well-calibrated; ECE is the size-weighted gap from it.
function ReliabilityCurve() {
  const S = 320; // logical viewBox size (square plot)
  const pad = 34; // inner padding for axes/labels
  const plot = S - pad * 2;
  const x = (v: number) => pad + v * plot;
  const y = (v: number) => pad + (1 - v) * plot; // invert: 0 bottom, 1 top
  const grid = [0, 0.25, 0.5, 0.75, 1];

  // radius by bin count (sqrt scale so a 159-count point doesn't dwarf a 1)
  const r = (count: number) => 4 + Math.sqrt(count) * 0.9;

  return (
    <figure className="m-0 flex flex-col gap-3">
      <svg
        viewBox={`0 0 ${S} ${S}`}
        role="img"
        aria-label="Reliability diagram: predicted confidence versus observed accuracy. Measured points hug the perfect-calibration diagonal."
        className="w-full"
        style={{ maxWidth: 380 }}
      >
        {/* gridlines */}
        {grid.map((g) => (
          <g key={`g-${g}`}>
            <line
              x1={x(g)}
              y1={y(0)}
              x2={x(g)}
              y2={y(1)}
              stroke="var(--ax-border-neutral)"
              strokeWidth={1}
            />
            <line
              x1={x(0)}
              y1={y(g)}
              x2={x(1)}
              y2={y(g)}
              stroke="var(--ax-border-neutral)"
              strokeWidth={1}
            />
          </g>
        ))}

        {/* perfect-calibration diagonal */}
        <line
          x1={x(0)}
          y1={y(0)}
          x2={x(1)}
          y2={y(1)}
          stroke="var(--ax-fg-faint)"
          strokeWidth={1.5}
          strokeDasharray="5 4"
        />

        {/* contract-audit measured points (emerald) */}
        {CONTRACT.bins.map((b, i) => (
          <circle
            key={`c-${i}`}
            cx={x(b.conf)}
            cy={y(b.acc)}
            r={r(b.count)}
            fill="var(--ax-emerald-dim)"
            stroke="var(--ax-emerald)"
            strokeWidth={1.5}
            style={{ filter: "drop-shadow(0 0 4px var(--ax-emerald))" }}
          />
        ))}

        {/* NDA measured points (gold) */}
        {NDA.bins.map((b, i) => (
          <circle
            key={`n-${i}`}
            cx={x(b.conf)}
            cy={y(b.acc)}
            r={r(b.count)}
            fill="var(--ax-gold-dim)"
            stroke="var(--ax-gold)"
            strokeWidth={1.5}
            style={{ filter: "drop-shadow(0 0 4px var(--ax-gold))" }}
          />
        ))}

        {/* axis ticks + labels */}
        {grid.map((g) => (
          <g key={`t-${g}`}>
            <text
              x={x(g)}
              y={y(0) + 16}
              textAnchor="middle"
              className="tnum"
              fontFamily="var(--font-mono, monospace)"
              fontSize="9"
              fill="var(--ax-fg-muted)"
            >
              {g.toFixed(2)}
            </text>
            <text
              x={x(0) - 8}
              y={y(g) + 3}
              textAnchor="end"
              className="tnum"
              fontFamily="var(--font-mono, monospace)"
              fontSize="9"
              fill="var(--ax-fg-muted)"
            >
              {g.toFixed(2)}
            </text>
          </g>
        ))}

        {/* "perfect calibration" annotation along the diagonal */}
        <text
          x={x(0.5) + 6}
          y={y(0.5) - 8}
          fontFamily="var(--font-mono, monospace)"
          fontSize="9"
          fill="var(--ax-fg-faint)"
          transform={`rotate(-45 ${x(0.5)} ${y(0.5)})`}
          textAnchor="middle"
        >
          perfect calibration
        </text>

        {/* axis titles */}
        <text
          x={x(0.5)}
          y={S - 4}
          textAnchor="middle"
          fontFamily="var(--font-mono, monospace)"
          fontSize="9.5"
          fontWeight="600"
          fill="var(--ax-fg-muted)"
        >
          PREDICTED CONFIDENCE
        </text>
        <text
          x={12}
          y={x(0.5)}
          textAnchor="middle"
          fontFamily="var(--font-mono, monospace)"
          fontSize="9.5"
          fontWeight="600"
          fill="var(--ax-fg-muted)"
          transform={`rotate(-90 12 ${x(0.5)})`}
        >
          OBSERVED ACCURACY
        </text>
      </svg>

      {/* legend + ECE annotation */}
      <figcaption className="flex flex-col gap-2">
        <div className="flex flex-wrap items-center gap-x-5 gap-y-1.5">
          <span className="inline-flex items-center gap-1.5 font-mono text-[11px] text-fg-muted">
            <span className="inline-block h-2.5 w-2.5 rounded-full border border-emerald bg-emerald-dim" />
            Contract-audit · ECE {CONTRACT.ece.toFixed(3)}
          </span>
          <span className="inline-flex items-center gap-1.5 font-mono text-[11px] text-fg-muted">
            <span className="inline-block h-2.5 w-2.5 rounded-full border border-gold bg-gold-dim" />
            NDA · ECE {NDA.ece.toFixed(3)}
          </span>
        </div>
        <p className="font-mono text-[11px] leading-[1.7] text-fg-faint">
          Point area is proportional to how many graded claims fell in that
          confidence bin. Points sit on the diagonal — the verifier&apos;s stated
          confidence matches how often it is actually right.
        </p>
      </figcaption>
    </figure>
  );
}

export function Research() {
  return (
    <section
      id="research"
      className="mx-auto max-w-6xl px-5 py-20 sm:px-8 sm:py-24"
    >
      <div className="ax-fade-up mb-12 max-w-2xl">
        <SectionIntro label="The proof · measured, not projected">
          A calibrated lie-detector for paid work
        </SectionIntro>
        <p className="mt-4 font-mono text-[13px] leading-[1.8] text-fg-muted">
          The whole product rests on one claim:{" "}
          <span className="text-emerald">
            fabricated work pays exactly $0, and honest work always gets paid
          </span>
          . Here is the evidence — caught, missed, wrongly held back, and how
          well-calibrated the verifier&apos;s confidence is. Every figure is read
          from an evaluation in the repo, with its sample size shown.
        </p>
      </div>

      <div className="grid grid-cols-1 gap-10 lg:grid-cols-[1.15fr_1fr] lg:gap-12">
        {/* LEFT — headline metrics as big numerals */}
        <div className="flex flex-col gap-8">
          {/* The differentiator, given the most weight */}
          <div className="rounded-lg border border-hud bg-surface p-6 ax-brackets">
            <div className="mb-5 flex items-center gap-2.5">
              <span className="text-emerald">
                <Shield size={16} />
              </span>
              <span className="font-display text-[11px] font-bold uppercase tracking-[0.16em] text-fg-muted">
                The differentiator
              </span>
            </div>
            <span className="tnum font-display text-[64px] font-black leading-none text-emerald sm:text-[80px]">
              <CountUp value={2.5} decimals={1} suffix="%" />
            </span>
            <p className="mt-3 font-display text-[13px] font-bold uppercase tracking-[0.1em] text-fg">
              False-withhold rate
            </p>
            <p className="mt-2 max-w-md font-mono text-[12.5px] leading-[1.75] text-fg-muted">
              In plain English: the verifier wrongly withheld pay on just{" "}
              <span className="text-emerald">2.5% of genuine work</span> — and
              never once on NDA. An honest agent almost always gets paid.
            </p>
            <p className="tnum mt-3 font-mono text-[11px] text-fg-faint">
              2 of 81 genuine contract-audit deliverables wrongly held back
              (2.5%); 0 of 12 on NDA. Locked in METRICS_LOCK.md.
            </p>
          </div>

          {/* The three supporting headline numbers, per job type */}
          <div className="grid grid-cols-1 gap-x-8 gap-y-7 sm:grid-cols-2">
            <Metric
              tone="emerald"
              value={<CountUp value={100} suffix="%" />}
              label="Catch-rate"
              fraction="81 / 81 contract-audit fabrications caught · NDA 10 / 10"
              plain="Every seeded fabrication was caught — against an LLM inventing plausible-but-false claims. 100% is against this adversary, not 'unbeatable.'"
            />
            <Metric
              tone="fg"
              value={<CountUp value={97.6} decimals={1} suffix="%" />}
              label="Precision"
              fraction="contract-audit: 81 / 83 withholds were truly fabricated · NDA: 10 / 10"
              plain="When it withholds pay, it is almost always right to. Few honest deliverables get caught in the net."
            />
            <Metric
              tone="emerald"
              value={<CountUp value={0.015} decimals={3} />}
              label="Calibration · ECE"
              fraction="contract-audit, N=162 · NDA ECE 0.005, N=22"
              plain="Expected calibration error: how far the verifier's confidence drifts from reality. ~0.01 means a '90% sure' is right about 90% of the time."
            />
            <Metric
              tone="gold"
              value={
                <span>
                  <CountUp value={2} />
                  <span className="text-fg-faint"> txs</span>
                </span>
              }
              label="Real settlement"
              fraction="live x402 on Base Sepolia (testnet) · pay_fraction 0.75"
              plain="Verify → settle is live and on-chain: the worker is paid per verified claim, the rest withheld. Mechanism real; amounts are test funds."
            />
          </div>
        </div>

        {/* RIGHT — the reliability curve */}
        <div className="flex flex-col gap-5 rounded-lg border border-hud-neutral bg-surface p-6">
          <div className="flex flex-col gap-1">
            <Eyebrow tone="emerald" className="mb-1">
              Reliability diagram
            </Eyebrow>
            <p className="font-mono text-[12px] leading-[1.7] text-fg-muted">
              Does the verifier know what it knows? The closer the measured
              points hug the diagonal, the better-calibrated it is.
            </p>
          </div>
          <ReliabilityCurve />
        </div>
      </div>

      {/* HONESTY CAVEAT — sample sizes + measured-not-projected, stated plainly */}
      <div className="mt-12 rounded-lg border border-hud-neutral bg-surface-2 p-5">
        <Eyebrow tone="gold" className="mb-3">
          Honesty caveat · read this
        </Eyebrow>
        <p className="font-mono text-[12px] leading-[1.85] text-fg-muted">
          These are <span className="text-fg">measured, not projected</span>.
          Contract-audit: 162 graded claims (81 fabricated + 81 genuine),
          source{" "}
          <span className="text-fg-faint">data/eval/catch_rate_report.json</span>
          . NDA: 22 hand-labeled cases (10 fabricated + 12 genuine), source{" "}
          <span className="text-fg-faint">
            data/eval/nda_catch_rate_report.json
          </span>
          . The NDA set is deliberately small (N=22) — we show the N rather than
          hide it. &ldquo;100% catch-rate&rdquo; is against one adversary (an LLM
          generating plausible-but-false claims); it means caught-all-of-these,
          not unbeatable. Settlement amounts are testnet (Base Sepolia) test
          USDC; the verify-then-settle mechanism is live. Headline numbers are
          locked in <span className="text-fg-faint">METRICS_LOCK.md</span> and
          regenerated from the named runs.
        </p>
      </div>
    </section>
  );
}
