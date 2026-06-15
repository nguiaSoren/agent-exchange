"use client";

import type { JobKind } from "@/lib/events";
import {
  HudPanel,
  Eyebrow,
  NeonButton,
  LiveDot,
  Bolt,
  Coin,
  Robot,
} from "@/components/hud";

interface JobCardProps {
  kind: JobKind;
  document: string;
  budget: number;
  demoMode: boolean;
  running: boolean;
  loadingSample: boolean;
  onKind: (k: JobKind) => void;
  onDocument: (d: string) => void;
  onBudget: (b: number) => void;
  onDemoMode: (v: boolean) => void;
  onRun: () => void;
}

const KINDS: { value: JobKind; label: string; blurb: string }[] = [
  { value: "contract-audit", label: "Contract audit", blurb: "Vendor MSA clause review" },
  { value: "nda-review", label: "NDA review", blurb: "Mutual NDA risk pass" },
];

function FieldLabel({ children }: { children: React.ReactNode }) {
  return (
    <span className="font-mono text-[10px] font-medium uppercase tracking-[0.16em] text-fg-faint">
      {children}
    </span>
  );
}

export function JobCard(props: JobCardProps) {
  const {
    kind,
    document,
    budget,
    demoMode,
    running,
    loadingSample,
    onKind,
    onDocument,
    onBudget,
    onDemoMode,
    onRun,
  } = props;

  return (
    <HudPanel
      eyebrow="OPERATOR CONSOLE"
      tone="emerald"
      title={
        <span className="flex items-center gap-2.5">
          <span className="text-emerald-glow">
            <Bolt size={18} />
          </span>
          POST A JOB
        </span>
      }
      right={
        running ? (
          <Eyebrow live tone="emerald">
            DISPATCHING
          </Eyebrow>
        ) : null
      }
    >
      <div className="flex flex-col gap-6">
        <div className="flex flex-wrap items-start justify-between gap-x-8 gap-y-6">
          {/* Kind */}
          <div className="flex flex-col gap-2.5">
            <FieldLabel>Job kind</FieldLabel>
            <div className="flex gap-2">
              {KINDS.map((k) => {
                const active = k.value === kind;
                return (
                  <button
                    key={k.value}
                    type="button"
                    disabled={running}
                    onClick={() => onKind(k.value)}
                    aria-pressed={active}
                    className={`ax-press min-h-[44px] rounded-md border px-4 py-2.5 text-left outline-none transition focus-visible:ring-2 focus-visible:ring-emerald/70 focus-visible:ring-offset-2 focus-visible:ring-offset-canvas disabled:cursor-not-allowed disabled:opacity-50 ${
                      active
                        ? "border-emerald bg-emerald-dim shadow-glow-emerald"
                        : "border-hud-neutral bg-surface-2 hover:border-hud"
                    }`}
                  >
                    <div
                      className={`font-display text-[12px] font-bold uppercase tracking-[0.08em] ${
                        active ? "text-emerald-glow" : "text-fg-muted"
                      }`}
                    >
                      {k.label}
                    </div>
                    <div className="mt-0.5 font-mono text-[10.5px] text-fg-faint">
                      {k.blurb}
                    </div>
                  </button>
                );
              })}
            </div>
          </div>

          {/* Budget */}
          <div className="flex flex-col gap-2.5">
            <FieldLabel>Budget · USDC</FieldLabel>
            <div className="flex items-center gap-3">
              <input
                type="range"
                min={2}
                max={30}
                step={1}
                value={budget}
                disabled={running}
                aria-label="Job budget in USDC"
                onChange={(e) => onBudget(Number(e.target.value))}
                className="ax-range h-1 w-36 cursor-pointer appearance-none rounded-full outline-none focus-visible:ring-2 focus-visible:ring-emerald/70 focus-visible:ring-offset-2 focus-visible:ring-offset-canvas disabled:opacity-50"
              />
              <span className="tnum inline-flex min-h-[44px] w-[88px] items-center justify-center gap-1.5 rounded-md border border-gold/50 bg-gold-dim px-2 py-1.5 font-display text-[14px] font-bold text-gold">
                <Coin size={13} />
                {budget.toFixed(2)}
              </span>
            </div>
          </div>

          {/* Run + demo */}
          <div className="flex flex-col gap-2.5">
            <FieldLabel>Run</FieldLabel>
            <div className="flex items-center gap-4">
              <label className="flex min-h-[44px] cursor-pointer items-center gap-2.5 font-mono text-[11px] uppercase tracking-[0.08em] text-fg-muted">
                <span className="relative inline-flex">
                  <input
                    type="checkbox"
                    checked={demoMode}
                    disabled={running}
                    onChange={(e) => onDemoMode(e.target.checked)}
                    className="peer sr-only"
                  />
                  <span className="h-5 w-9 rounded-full bg-surface-2 ring-1 ring-inset ring-hud-neutral transition-colors duration-200 ease-ax-out peer-checked:bg-emerald-dim peer-checked:ring-emerald peer-focus-visible:ring-2 peer-focus-visible:ring-emerald/70" />
                  <span className="absolute left-0.5 top-0.5 h-4 w-4 rounded-full bg-fg-faint shadow-sm transition-transform duration-200 ease-ax-out peer-checked:translate-x-4 peer-checked:bg-emerald-glow" />
                </span>
                <span>Demo mode</span>
              </label>
              <NeonButton
                type="button"
                variant="primary"
                onClick={onRun}
                disabled={running}
                className="min-h-[44px]"
              >
                {running ? (
                  <>
                    <LiveDot tone="emerald" size={8} />
                    Running…
                  </>
                ) : (
                  <>
                    <Bolt size={15} />
                    Run job
                  </>
                )}
              </NeonButton>
            </div>
          </div>
        </div>

        {/* Document */}
        <div>
          <div className="mb-2 flex items-center justify-between">
            <FieldLabel>Document</FieldLabel>
            {loadingSample && (
              <Eyebrow live tone="emerald">
                Loading sample…
              </Eyebrow>
            )}
          </div>
          <div className="relative">
            <span className="pointer-events-none absolute right-3 top-3 text-fg-faint/60">
              <Robot size={14} />
            </span>
            <textarea
              value={document}
              disabled={running}
              onChange={(e) => onDocument(e.target.value)}
              rows={4}
              spellCheck={false}
              placeholder="Paste the contract or NDA text to put under audit…"
              className="ax-scroll caret-emerald-glow w-full resize-y rounded-md border border-hud-neutral bg-canvas p-4 pr-10 font-mono text-[12px] leading-relaxed text-fg outline-none transition-colors duration-150 ease-ax-out placeholder:text-fg-faint/60 focus:border-emerald focus:shadow-glow-emerald disabled:opacity-60"
            />
          </div>
        </div>
      </div>
    </HudPanel>
  );
}
