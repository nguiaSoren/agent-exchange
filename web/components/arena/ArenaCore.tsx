"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import type { DocumentEvent, FindingEvent } from "@/lib/events";
import type { RunState } from "@/lib/runState";
import { Gavel, Shield } from "@/components/hud";
import { verdictStyle } from "@/lib/ui";
import styles from "./arena.module.css";

/**
 * The focal center of the ring: the JOB (document title + kind + gold budget)
 * and the VERIFIER, which is where claims get judged. During Verify it shows a
 * live readout of the current claim, its evidence quote, verdict + confidence.
 * It is the substantive replacement for the old document/verify panels.
 */
export function ArenaCore({
  layout,
  document,
  findings,
  stageActive,
  finished,
  emphasized = false,
  onSelect,
}: {
  layout: { cx: number; cy: number; coreR: number };
  document: DocumentEvent | null;
  findings: FindingEvent[];
  /** The currently active stage name (drives the core's mode). */
  stageActive: string | null;
  finished: boolean;
  /** True during the "catch" beat — a subtle extra lift atop the red shake. */
  emphasized?: boolean;
  /** Click / Enter / Space → open the run (job + verifier) detail drawer. */
  onSelect?: () => void;
}) {
  const latest = findings.length ? findings[findings.length - 1] : null;
  const inVerify = stageActive === "Verify" || (findings.length > 0 && !finished);

  // Tally for the verifier sub-caption.
  const tally = useMemo(() => {
    let real = 0,
      partial = 0,
      fake = 0;
    for (const f of findings) {
      if (f.verdict === "confirmed") real++;
      else if (f.verdict === "partial") partial++;
      else fake++;
    }
    return { real, partial, fake };
  }, [findings]);

  const diameter = layout.coreR * 2;
  const isFake = latest?.verdict === "unsupported";
  // T2-5: the pre-run empty state — give the dormant court a calm breath so it
  // doesn't read as dead. Only when there's no job posted and nothing to grade.
  const idleCourt = !document && !inVerify && !finished;

  // Fire a one-beat shake exactly on the transition INTO fabricated state (B5).
  const prevFakeRef = useRef(false);
  const [coreShaking, setCoreShaking] = useState(false);
  useEffect(() => {
    const wasAlreadyFake = prevFakeRef.current;
    prevFakeRef.current = isFake;
    if (isFake && !wasAlreadyFake) {
      setCoreShaking(true);
      const t = window.setTimeout(() => setCoreShaking(false), 700);
      return () => window.clearTimeout(t);
    }
  }, [isFake]);

  return (
    <div
      role={onSelect ? "button" : undefined}
      tabIndex={onSelect ? 0 : undefined}
      aria-label={
        onSelect
          ? document
            ? `Open run detail: ${document.title}`
            : "Open run detail"
          : undefined
      }
      onClick={onSelect}
      onKeyDown={(e) => {
        if (!onSelect) return;
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onSelect();
        }
      }}
      className={`${styles.coreEnter} ${coreShaking ? styles.fakeShake : ""} ${onSelect ? "cursor-pointer transition-transform duration-200 ease-ax-out hover:scale-[1.02] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald/70" : ""} absolute z-20 flex flex-col items-center justify-center rounded-full border text-center`}
      style={{
        left: layout.cx,
        top: layout.cy,
        width: diameter,
        height: diameter,
        transform: "translate(-50%, -50%)",
        // A dark core WELL with a faint emerald lift at the crown — the focal
        // verifier disc on the dark court. (`--ax-surface-rgb` re-themes dark
        // under `.ax-court`, so the disc reads as a deep panel, not a white card.)
        background:
          "radial-gradient(circle at 50% 30%, rgb(var(--ax-surface-2-rgb)), rgb(var(--ax-canvas-rgb)))",
        borderColor: isFake
          ? "var(--ax-red)"
          : inVerify
            ? "var(--ax-emerald)"
            : "rgb(var(--ax-border-neutral-rgb) / 0.12)",
        boxShadow: isFake
          ? emphasized
            ? "var(--ax-glow-red), 0 0 0 6px rgba(255, 59, 92, 0.18)"
            : "var(--ax-glow-red)"
          : inVerify
            ? "var(--ax-glow-emerald)"
            : "inset 0 0 30px -10px rgba(0,0,0,0.7), 0 14px 32px -18px rgba(0,0,0,0.6)",
        padding: Math.max(10, layout.coreR * 0.16),
      }}
    >
      {/* Slow conic sweep — the "verifier is alive" tell, behind the content. */}
      <span
        aria-hidden
        className={`${styles.coreSweep} pointer-events-none absolute inset-1 rounded-full`}
        style={{
          background:
            "conic-gradient(from 0deg, transparent 0deg, rgba(0,214,122,0.16) 40deg, transparent 90deg)",
          opacity: inVerify ? 1 : 0.4,
        }}
      />

      {/* T2-5 — idle court breath: a calm emerald glow that breathes (opacity)
          while the court waits for a job, so the empty stage feels alive but
          quiet. `ax-pulse` is compositor-only + killed under reduced motion. */}
      {idleCourt && (
        <span
          aria-hidden
          className="ax-pulse pointer-events-none absolute -inset-1 rounded-full"
          style={{
            boxShadow: "0 0 36px -10px rgba(0, 214, 122, 0.45)",
          }}
        />
      )}

      <div className="relative flex flex-col items-center gap-1 px-1">
        {inVerify || finished ? (
          <CoreVerifierReadout
            latest={latest}
            tally={tally}
            coreR={layout.coreR}
          />
        ) : (
          <CoreJob document={document} coreR={layout.coreR} />
        )}
      </div>
    </div>
  );
}

function CoreJob({
  document,
  coreR,
}: {
  document: DocumentEvent | null;
  coreR: number;
}) {
  const compact = coreR < 84;
  return (
    <>
      <span className="inline-flex items-center gap-1.5 font-mono text-[9px] uppercase tracking-[0.2em] text-fg-faint">
        <Gavel size={12} />
        The Job
      </span>
      {document ? (
        <>
          <span
            className="mt-0.5 line-clamp-2 font-display font-bold leading-tight text-fg"
            style={{ fontSize: compact ? 10 : 12, maxWidth: coreR * 1.7 }}
          >
            {document.title}
          </span>
          <span className="mt-1 font-mono text-[9px] uppercase tracking-[0.12em] text-fg-muted">
            {document.kind}
          </span>
          <span className="mt-1.5 font-mono text-[13px] font-bold tabular-nums text-gold">
            ${document.budget_usd.toFixed(2)}
          </span>
          <span className="font-mono text-[8px] uppercase tracking-[0.16em] text-fg-faint">
            bounty
          </span>
        </>
      ) : (
        <span className="mt-1 max-w-[120px] font-mono text-[10px] leading-relaxed text-fg-faint">
          Awaiting a posted job
        </span>
      )}
    </>
  );
}

function CoreVerifierReadout({
  latest,
  tally,
  coreR,
}: {
  latest: FindingEvent | null;
  tally: { real: number; partial: number; fake: number };
  coreR: number;
}) {
  const compact = coreR < 84;
  const vs = latest ? verdictStyle(latest.verdict) : null;
  return (
    <>
      <span className="inline-flex items-center gap-1.5 font-mono text-[9px] uppercase tracking-[0.2em] text-fg-faint">
        <Shield size={12} />
        Verifier
      </span>

      {latest && vs ? (
        <>
          <span
            className="mt-1 inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 font-mono text-[9px] font-bold uppercase tracking-[0.12em]"
            style={{ color: vs.fg, borderColor: vs.fg, background: vs.bg }}
          >
            §{latest.clause_ref} · {vs.label === "Fake" ? "Fabricated" : vs.label}
          </span>
          {!compact && (
            <span
              className="mt-1.5 line-clamp-3 px-1 font-mono text-[9px] leading-snug text-fg-muted"
              style={{ maxWidth: coreR * 1.75 }}
            >
              {latest.claim}
            </span>
          )}
          {latest.evidence_quote && !compact && (
            <span
              className="mt-1 line-clamp-2 border-l px-1.5 text-left font-mono text-[8.5px] italic leading-snug text-fg-faint"
              style={{ borderColor: vs.fg, maxWidth: coreR * 1.7 }}
            >
              “{latest.evidence_quote}”
            </span>
          )}
          <span className="mt-1 font-mono text-[8.5px] tabular-nums text-fg-faint">
            confidence {(latest.confidence * 100).toFixed(0)}%
          </span>
        </>
      ) : (
        <span className="mt-1 font-mono text-[10px] text-fg-faint">
          Grading claims…
        </span>
      )}

      <span className="mt-1.5 inline-flex items-center gap-2 font-mono text-[9px] tabular-nums">
        <span className="text-emerald-glow">{tally.real}✓</span>
        <span className="text-gold">{tally.partial}~</span>
        <span className="text-danger">{tally.fake}✗</span>
      </span>
    </>
  );
}
