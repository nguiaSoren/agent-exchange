"use client";

import { useMemo, useState } from "react";
import type { DocumentEvent, FindingEvent } from "@/lib/events";
import { prettyWorker, verdictStyle } from "@/lib/ui";
import {
  HudPanel,
  Eyebrow,
  SegmentBar,
  VerdictGlyph,
  Gavel,
  Check,
  Tilde,
  Cross,
} from "@/components/hud";

interface VerifyPanelProps {
  document: DocumentEvent | null;
  findings: FindingEvent[];
}

interface Highlight {
  start: number;
  end: number;
  finding: FindingEvent;
}

/** Locate each finding's evidence_quote inside the document text (first match). */
function computeHighlights(text: string, findings: FindingEvent[]): Highlight[] {
  const hs: Highlight[] = [];
  for (const f of findings) {
    const q = (f.evidence_quote ?? "").trim();
    if (!q) continue;
    const idx = text.indexOf(q);
    if (idx === -1) continue;
    hs.push({ start: idx, end: idx + q.length, finding: f });
  }
  hs.sort((a, b) => a.start - b.start);
  const out: Highlight[] = [];
  let cursor = -1;
  for (const h of hs) {
    if (h.start >= cursor) {
      out.push(h);
      cursor = h.end;
    }
  }
  return out;
}

export function VerifyPanel({ document, findings }: VerifyPanelProps) {
  const [active, setActive] = useState<number | null>(null);
  const text = document?.document_text ?? "";

  const highlights = useMemo(
    () => computeHighlights(text, findings),
    [text, findings]
  );

  const segments = useMemo(() => {
    if (!text) return [] as { text: string; h: Highlight | null }[];
    const segs: { text: string; h: Highlight | null }[] = [];
    let cursor = 0;
    for (const h of highlights) {
      if (h.start > cursor)
        segs.push({ text: text.slice(cursor, h.start), h: null });
      segs.push({ text: text.slice(h.start, h.end), h });
      cursor = h.end;
    }
    if (cursor < text.length) segs.push({ text: text.slice(cursor), h: null });
    return segs;
  }, [text, highlights]);

  return (
    <HudPanel
      eyebrow="VERIFIER · CLAIM vs DOCUMENT"
      live={findings.length > 0}
      tone="emerald"
      padded={false}
      title={
        <span className="flex items-center gap-2.5">
          <span className="text-emerald-glow">
            <Gavel size={18} />
          </span>
          VERIFICATION
        </span>
      }
      right={
        <div className="flex flex-col items-end gap-1.5">
          {document && (
            <span className="max-w-[220px] truncate font-mono text-[11px] text-fg-muted">
              {document.title}
            </span>
          )}
          <VerdictTally findings={findings} />
        </div>
      }
    >
      <div className="grid grid-cols-1 lg:grid-cols-[1.05fr_1fr]">
        {/* Document with washed evidence spans */}
        <div className="ax-scroll max-h-[560px] overflow-y-auto border-b border-hud-neutral px-7 py-6 lg:border-b-0 lg:border-r">
          {!document ? (
            <Placeholder text="The document under audit renders here once the job runs." />
          ) : (
            <article className="whitespace-pre-wrap font-mono text-[12.5px] leading-[1.9] text-fg-muted">
              {segments.map((seg, i) => {
                if (!seg.h) return <span key={i}>{seg.text}</span>;
                const idx = findings.indexOf(seg.h.finding);
                const style = verdictStyle(seg.h.finding.verdict);
                const isActive = active === idx;
                return (
                  <mark
                    key={i}
                    onMouseEnter={() => setActive(idx)}
                    onMouseLeave={() => setActive(null)}
                    className="ax-press cursor-pointer rounded-[3px] px-0.5"
                    style={{
                      background: style.highlight,
                      color: "#e8fbf1",
                      boxShadow: isActive
                        ? `inset 0 0 0 1px ${style.border}, 0 0 12px -2px ${style.border}`
                        : `inset 0 0 0 1px ${style.border}33`,
                    }}
                  >
                    {seg.text}
                  </mark>
                );
              })}
            </article>
          )}
        </div>

        {/* Graded findings */}
        <div className="ax-scroll max-h-[560px] overflow-y-auto px-5 py-5">
          {findings.length === 0 ? (
            <Placeholder text="Graded findings appear here as the verifier checks each claim against the text." />
          ) : (
            <ul className="space-y-3">
              {findings.map((f, i) => (
                <FindingCard
                  key={i}
                  f={f}
                  index={i}
                  active={active === i}
                  onEnter={() => setActive(i)}
                  onLeave={() => setActive(null)}
                />
              ))}
            </ul>
          )}
        </div>
      </div>
    </HudPanel>
  );
}

function FindingCard({
  f,
  index,
  active,
  onEnter,
  onLeave,
}: {
  f: FindingEvent;
  index: number;
  active: boolean;
  onEnter: () => void;
  onLeave: () => void;
}) {
  const style = verdictStyle(f.verdict);
  const fake = f.verdict === "unsupported";
  const partial = f.verdict === "partial";
  const tone = fake ? "red" : partial ? "gold" : "emerald";

  return (
    <li
      onMouseEnter={onEnter}
      onMouseLeave={onLeave}
      className={`ax-stagger ax-card ${
        fake ? "ax-card-red" : partial ? "ax-card-gold" : ""
      } relative overflow-hidden rounded-lg border bg-surface-2 p-4`}
      style={{
        // @ts-expect-error CSS custom prop for stagger delay
        "--index": index,
        borderColor: fake ? "#ff3b5c" : active ? style.border : "rgba(255,255,255,0.06)",
        boxShadow: active
          ? `0 0 0 1px ${style.border}, 0 0 18px -6px ${style.border}`
          : fake
            ? "0 0 0 1px rgba(255,59,92,0.4)"
            : "none",
      }}
    >
      <div className="flex items-start gap-3">
        {/* verdict glyph tile */}
        <span
          className="mt-px flex h-7 w-7 shrink-0 items-center justify-center rounded-md"
          style={{
            background: style.bg,
            color: style.fg,
            boxShadow: `inset 0 0 0 1px ${style.border}55`,
          }}
        >
          <VerdictGlyph glyph={style.glyph} size={15} />
        </span>

        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span
              className={`font-display text-[11px] font-bold uppercase tracking-[0.14em] ${
                fake ? "ax-glitch-live" : ""
              }`}
              style={{ color: style.fg }}
            >
              {style.label}
            </span>
            {fake && (
              <span
                className="rounded-[4px] px-1.5 py-0.5 font-mono text-[9px] font-medium uppercase tracking-[0.1em]"
                style={{
                  background: "rgba(255,59,92,0.18)",
                  color: "#ff3b5c",
                  boxShadow: "inset 0 0 0 1px #ff3b5c",
                }}
              >
                Withheld · $0
              </span>
            )}
            {f.clause_ref && (
              <span className="rounded-[4px] border border-hud-neutral bg-canvas px-1.5 py-0.5 font-mono text-[10px] text-fg-muted">
                §{f.clause_ref}
              </span>
            )}
            <span className="tnum ml-auto font-mono text-[10px] text-fg-faint">
              {(f.confidence * 100).toFixed(0)}% conf
            </span>
          </div>

          <p className="mt-2 text-[13px] leading-relaxed text-fg">{f.claim}</p>

          <div className="mt-1.5 flex items-center gap-2">
            <span className="font-mono text-[10px] uppercase tracking-[0.1em] text-fg-faint">
              {prettyWorker(f.worker)}
            </span>
          </div>

          {/* confidence bar */}
          <div className="mt-2.5">
            <SegmentBar value={f.confidence} tone={tone} variant="smooth" />
          </div>

          {f.evidence_quote && (
            <blockquote
              className="mt-3 border-l-2 pl-3 text-[11.5px] italic leading-relaxed"
              style={{
                borderColor: style.border,
                color: fake ? "#ff3b5c" : "#7e9d90",
              }}
            >
              &ldquo;{f.evidence_quote}&rdquo;
            </blockquote>
          )}
        </div>
      </div>
    </li>
  );
}

function Placeholder({ text }: { text: string }) {
  return (
    <div className="flex h-full min-h-[240px] items-center justify-center px-8 text-center font-mono text-[12px] leading-relaxed text-fg-faint">
      {text}
    </div>
  );
}

function VerdictTally({ findings }: { findings: FindingEvent[] }) {
  const c = findings.filter((f) => f.verdict === "confirmed").length;
  const p = findings.filter((f) => f.verdict === "partial").length;
  const u = findings.filter((f) => f.verdict === "unsupported").length;
  if (findings.length === 0) return null;
  return (
    <div className="flex items-center gap-2">
      <Tally n={c} kind="real" />
      <Tally n={p} kind="partial" />
      <Tally n={u} kind="fake" />
    </div>
  );
}

function Tally({ n, kind }: { n: number; kind: "real" | "partial" | "fake" }) {
  const map = {
    real: { fg: "#2bff9a", bg: "rgba(0,214,122,0.18)", border: "#00d67a", icon: <Check size={13} /> },
    partial: { fg: "#ffc233", bg: "rgba(255,194,51,0.18)", border: "#ffc233", icon: <Tilde size={13} /> },
    fake: { fg: "#ff3b5c", bg: "rgba(255,59,92,0.18)", border: "#ff3b5c", icon: <Cross size={13} /> },
  }[kind];
  return (
    <span
      className="tnum inline-flex items-center gap-1.5 rounded-md px-2 py-1 font-mono text-[12px] font-medium"
      style={{
        background: map.bg,
        color: map.fg,
        boxShadow: `inset 0 0 0 1px ${map.border}55`,
      }}
    >
      {map.icon}
      {n}
    </span>
  );
}
