"use client";

import { useCallback, useRef, useState } from "react";
import {
  Eyebrow,
  LiveDot,
  NeonButton,
  VerdictGlyph,
  Shield,
  Coin,
} from "@/components/hud";
import { verdictStyle } from "@/lib/ui";
import { API_BASE } from "@/lib/stream";
import type { JobKind, Verdict } from "@/lib/events";

/* ─────────────────────────────────────────────────────────────────────── */
/*  Audit YOUR OWN contract — the LIVE judge-facing path.                   */
/*                                                                          */
/*  A judge pastes a real contract / NDA, the REAL backend verifier grades  */
/*  every claim against THEIR text, and they see "it caught a lie in MY     */
/*  document." Unlike the deterministic arena above, this hits the live     */
/*  endpoint (POST {API_BASE}/api/audit). The whole point is honesty: we    */
/*  render the real verdicts + evidence the verifier returns; a fabricated  */
/*  finding earns $0.                                                       */
/*                                                                          */
/*  Light editorial theme. Compositor-only motion; reduced-motion safe.     */
/* ─────────────────────────────────────────────────────────────────────── */

/** One finding row, mirroring the locked /api/audit response shape. */
interface AuditFinding {
  worker: string;
  clause_ref: string;
  claim: string;
  verdict: Verdict;
  confidence: number;
  evidence_quote: string | null;
}

/** Successful 200 response from POST /api/audit. */
interface AuditResult {
  kind: JobKind;
  n_findings: number;
  n_confirmed: number;
  n_partial: number;
  n_unsupported: number;
  gate_passed: boolean;
  catch_summary: string;
  est_cost_usd: number;
  findings: AuditFinding[];
}

type Phase = "idle" | "loading" | "done" | "error";

/** A user-resolved error message — we NEVER leave a dead spinner. */
interface AuditError {
  message: string;
  /** A muted secondary hint pointing back at the deterministic demo. */
  hint?: string;
}

/* Short, paste-free samples so a judge can one-click try. Kept deliberately
   small (the spirit of lib/mockRun.ts's docs, trimmed). */
const SAMPLE_CONTRACT = `MASTER SERVICES AGREEMENT

3. Limitation of Liability. Vendor's aggregate liability under this Agreement shall not exceed the total fees paid by Customer in the twelve (12) months preceding the event giving rise to the claim. Neither party is liable for indirect, incidental, or consequential damages.

7. Data Protection. Vendor shall notify Customer of a personal-data breach without undue delay and in any event within 72 hours.

8. Indemnification. Vendor shall indemnify Customer against third-party claims arising from Vendor's infringement of intellectual-property rights, subject to the limitation of liability in Section 3.`;

const SAMPLE_NDA = `MUTUAL NON-DISCLOSURE AGREEMENT

3. Obligations. The receiving party shall use the Confidential Information solely to evaluate the relationship and shall protect it with the same degree of care it uses for its own confidential information, but no less than reasonable care.

4. Term. The obligations of confidentiality survive for two (2) years from the date of disclosure.

7. No License. Nothing in this Agreement grants any license to any intellectual property of the disclosing party.`;

function sampleFor(kind: JobKind): string {
  return kind === "nda-review" ? SAMPLE_NDA : SAMPLE_CONTRACT;
}

const KIND_LABEL: Record<JobKind, string> = {
  "contract-audit": "Contract audit",
  "nda-review": "NDA review",
};

export function AuditYourContract() {
  const [kind, setKind] = useState<JobKind>("contract-audit");
  const [text, setText] = useState("");
  const [phase, setPhase] = useState<Phase>("idle");
  const [result, setResult] = useState<AuditResult | null>(null);
  const [error, setError] = useState<AuditError | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const fillSample = useCallback(() => {
    setText(sampleFor(kind));
    // Clearing a stale result keeps the panel honest after a sample swap.
    if (phase === "done" || phase === "error") {
      setPhase("idle");
      setResult(null);
      setError(null);
    }
  }, [kind, phase]);

  const run = useCallback(async () => {
    const document_text = text.trim();
    if (!document_text || phase === "loading") return;

    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    setPhase("loading");
    setResult(null);
    setError(null);

    try {
      const res = await fetch(`${API_BASE}/api/audit`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Accept: "application/json",
        },
        body: JSON.stringify({ kind, document_text }),
        signal: controller.signal,
      });

      if (res.ok) {
        const data = (await res.json()) as AuditResult;
        setResult(data);
        setPhase("done");
        return;
      }

      // Map the locked error contract to graceful, judge-readable copy.
      if (res.status === 429) {
        setError({
          message: "Live demo budget reached for today.",
          hint: "Try the deterministic demo above — it shows the full flow.",
        });
      } else if (res.status === 413) {
        setError({
          message: "That document's a bit long for the live demo.",
          hint: "Trim it under ~20k characters and try again.",
        });
      } else {
        setError({
          message: "Live audit is offline right now.",
          hint: "The deterministic demo above shows the full flow.",
        });
      }
      setPhase("error");
    } catch (err) {
      if (controller.signal.aborted) return; // a newer run superseded this one
      setError({
        message: "Live audit is offline right now.",
        hint: "The deterministic demo above shows the full flow.",
      });
      setPhase("error");
    }
  }, [text, kind, phase]);

  const swapKind = useCallback(
    (next: JobKind) => {
      if (next === kind) return;
      setKind(next);
      // If the textarea still holds the other kind's sample, swap it across so
      // the toggle stays one-click usable.
      setText((t) =>
        t === SAMPLE_CONTRACT || t === SAMPLE_NDA ? sampleFor(next) : t,
      );
    },
    [kind],
  );

  const charCount = text.trim().length;

  return (
    <section
      id="audit-your-contract"
      className="mx-auto max-w-6xl px-5 py-20 sm:px-8 sm:py-24"
    >
      <div className="ax-fade-up mb-12 max-w-2xl">
        <Eyebrow live tone="emerald" className="mb-4">
          Try it on your own contract · Live
        </Eyebrow>
        <h2 className="font-display text-[28px] font-bold leading-tight tracking-tight text-fg sm:text-[36px]">
          Audit a contract you bring
        </h2>
        <p className="mt-4 font-mono text-[13px] leading-[1.8] text-fg-muted">
          Paste a real contract or NDA — the same calibrated verifier grades
          every claim against your text.{" "}
          <span className="text-emerald">A fabricated finding earns $0.</span>
        </p>
      </div>

      <div className="ax-fade-up grid grid-cols-1 gap-6 lg:grid-cols-[1fr_1.05fr] lg:gap-8">
        {/* ── LEFT: the input ───────────────────────────────────────────── */}
        <div className="flex flex-col gap-4 rounded-lg border border-hud bg-surface p-6">
          {/* live badge — distinguishes this from the gold "demo" path above */}
          <div className="flex items-center justify-between gap-3">
            <span className="inline-flex items-center gap-2 font-mono text-[10px] font-medium uppercase tracking-[0.16em] text-emerald-glow">
              <LiveDot tone="emerald" size={7} />
              Live · real verifier
            </span>
            <span className="font-mono text-[10px] uppercase tracking-[0.12em] text-fg-faint">
              POST /api/audit
            </span>
          </div>

          {/* job-kind toggle */}
          <div
            role="radiogroup"
            aria-label="Job kind"
            className="grid grid-cols-2 gap-2 rounded-md border border-hud-neutral bg-surface-2 p-1"
          >
            {(["contract-audit", "nda-review"] as JobKind[]).map((k) => {
              const on = k === kind;
              return (
                <button
                  key={k}
                  type="button"
                  role="radio"
                  aria-checked={on}
                  onClick={() => swapKind(k)}
                  className={`ax-press rounded-[5px] px-3 py-2 font-display text-[11px] font-bold uppercase tracking-[0.1em] outline-none transition focus-visible:ring-2 focus-visible:ring-emerald/70 ${
                    on
                      ? "bg-emerald text-canvas shadow-glow-emerald"
                      : "bg-transparent text-fg-muted hover:text-fg"
                  }`}
                >
                  {KIND_LABEL[k]}
                </button>
              );
            })}
          </div>

          {/* the document */}
          <div className="flex flex-col gap-2">
            <div className="flex items-baseline justify-between gap-3">
              <label
                htmlFor="audit-doc"
                className="font-mono text-[10px] uppercase tracking-[0.14em] text-fg-faint"
              >
                Your {kind === "nda-review" ? "NDA" : "contract"} text
              </label>
              <button
                type="button"
                onClick={fillSample}
                className="font-mono text-[11px] text-emerald-glow underline-offset-2 outline-none transition hover:underline focus-visible:underline"
              >
                use a sample
              </button>
            </div>
            <textarea
              id="audit-doc"
              value={text}
              onChange={(e) => setText(e.target.value)}
              spellCheck={false}
              placeholder="Paste your contract or NDA here — or click “use a sample” to try it instantly."
              className="tnum h-64 w-full resize-y rounded-md border border-hud-neutral bg-surface-2 p-3 font-mono text-[12px] leading-[1.65] text-fg outline-none transition placeholder:text-fg-faint focus-visible:border-emerald focus-visible:ring-1 focus-visible:ring-emerald/40"
            />
            <div className="flex items-center justify-between gap-3">
              <span className="tnum font-mono text-[10.5px] text-fg-faint">
                {charCount.toLocaleString()} chars
              </span>
              <span className="font-mono text-[10.5px] text-fg-faint">
                quote-grounded · graded against your own text
              </span>
            </div>
          </div>

          <NeonButton
            type="button"
            onClick={run}
            disabled={charCount === 0 || phase === "loading"}
            className="w-full"
          >
            {phase === "loading" ? (
              <>
                <LiveDot tone="emerald" size={7} />
                Auditing…
              </>
            ) : (
              <>
                <Shield size={14} />
                Run live audit
              </>
            )}
          </NeonButton>
        </div>

        {/* ── RIGHT: the result panel ───────────────────────────────────── */}
        <div className="flex min-h-[22rem] flex-col rounded-lg border border-hud-neutral bg-surface p-6">
          {phase === "idle" && <IdleState />}
          {phase === "loading" && <LoadingState />}
          {phase === "error" && error && <ErrorState error={error} />}
          {phase === "done" && result && <ResultState result={result} />}
        </div>
      </div>

      {/* honesty caveat — same register as the Research section */}
      <p className="ax-fade-up mt-6 max-w-3xl font-mono text-[11px] leading-[1.75] text-fg-faint">
        This is the <span className="text-fg">live</span> path: your text is
        graded by the real verifier, and the verdicts + evidence shown are
        exactly what it returns — nothing is fabricated for the demo. The
        verifier withholds pay for unsupported claims; settlement amounts in the
        demo above are testnet (Base Sepolia).
      </p>
    </section>
  );
}

/* ── States ─────────────────────────────────────────────────────────────── */

function IdleState() {
  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-3 text-center">
      <span className="text-emerald opacity-60">
        <Shield size={28} />
      </span>
      <p className="max-w-xs font-mono text-[12px] leading-[1.7] text-fg-muted">
        Your findings appear here — each claim, its clause, and the exact quote
        from <span className="text-fg">your</span> document that supports it (or
        doesn&apos;t).
      </p>
    </div>
  );
}

function LoadingState() {
  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-4 text-center">
      <span className="inline-flex items-center gap-2.5">
        <LiveDot tone="emerald" size={9} />
        <span className="font-display text-[13px] font-bold uppercase tracking-[0.12em] text-emerald">
          Waking the verifier…
        </span>
      </span>
      <p className="max-w-xs font-mono text-[12px] leading-[1.7] text-fg-muted">
        First run can take ~40s — the verifier spins up, then grades every claim
        against your text. Hang tight; this is intentional, not stuck.
      </p>
      {/* compositor-only pulse rows; reduced-motion freezes them (ax-pulse is
          opacity-only and guarded in globals.css) */}
      <div className="mt-2 flex w-full max-w-xs flex-col gap-2" aria-hidden>
        <span className="ax-pulse h-3 w-full rounded-[3px] bg-surface-2" />
        <span className="ax-pulse h-3 w-4/5 rounded-[3px] bg-surface-2" />
        <span className="ax-pulse h-3 w-2/3 rounded-[3px] bg-surface-2" />
      </div>
    </div>
  );
}

function ErrorState({ error }: { error: AuditError }) {
  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-3 text-center">
      <span className="inline-flex h-9 w-9 items-center justify-center rounded-full border border-gold/40 bg-gold-dim text-gold">
        <Coin size={18} />
      </span>
      <p className="max-w-xs font-display text-[13px] font-bold text-fg">
        {error.message}
      </p>
      {error.hint && (
        <p className="max-w-xs font-mono text-[12px] leading-[1.7] text-fg-muted">
          {error.hint}
        </p>
      )}
    </div>
  );
}

function ResultState({ result }: { result: AuditResult }) {
  const caught = !result.gate_passed;
  return (
    <div className="ax-fade-up flex flex-1 flex-col gap-4">
      {/* result banner — the wow line */}
      {caught ? (
        <div className="flex items-start gap-3 rounded-md border border-danger/60 bg-danger-dim p-4">
          <span className="mt-0.5 shrink-0 text-danger">
            <VerdictGlyph glyph="cross" size={18} />
          </span>
          <div className="flex flex-col gap-1">
            <span className="font-display text-[13px] font-bold leading-snug text-danger">
              Fabrication caught — {result.n_unsupported} claim
              {result.n_unsupported === 1 ? "" : "s"} not supported by your
              document
            </span>
            <span className="tnum font-mono text-[11.5px] text-fg-muted">
              $0 would be paid · the whole deliverable is withheld
            </span>
          </div>
        </div>
      ) : (
        <div className="flex items-start gap-3 rounded-md border border-emerald/40 bg-emerald-dim p-4">
          <span className="mt-0.5 shrink-0 text-emerald">
            <VerdictGlyph glyph="check" size={18} />
          </span>
          <div className="flex flex-col gap-1">
            <span className="font-display text-[13px] font-bold leading-snug text-emerald">
              All {result.n_findings} claim
              {result.n_findings === 1 ? "" : "s"} verified against your document
            </span>
            <span className="tnum font-mono text-[11.5px] text-fg-muted">
              Honest work — payment would settle in full
            </span>
          </div>
        </div>
      )}

      {/* tally + cost */}
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5 border-b border-hud-neutral pb-3">
        <Tally count={result.n_confirmed} verdict="confirmed" />
        <Tally count={result.n_partial} verdict="partial" />
        <Tally count={result.n_unsupported} verdict="unsupported" />
        <span className="tnum ml-auto font-mono text-[10.5px] text-fg-faint">
          est. cost ${result.est_cost_usd.toFixed(4)}
        </span>
      </div>

      {/* the findings */}
      <ul className="flex flex-col gap-2.5">
        {result.findings.map((f, i) => (
          <FindingRow key={`${f.clause_ref}-${i}`} finding={f} />
        ))}
      </ul>

      {result.catch_summary && (
        <p className="mt-1 font-mono text-[11px] leading-[1.7] text-fg-faint">
          {result.catch_summary}
        </p>
      )}
    </div>
  );
}

function Tally({ count, verdict }: { count: number; verdict: Verdict }) {
  const s = verdictStyle(verdict);
  const label =
    verdict === "confirmed"
      ? "confirmed"
      : verdict === "partial"
        ? "partial"
        : "unsupported";
  return (
    <span className="inline-flex items-center gap-1.5">
      <span style={{ color: s.fg }}>
        <VerdictGlyph glyph={s.glyph} size={13} />
      </span>
      <span className="tnum font-mono text-[11.5px] text-fg-muted">
        <span className="text-fg">{count}</span> {label}
      </span>
    </span>
  );
}

function FindingRow({ finding }: { finding: AuditFinding }) {
  const s = verdictStyle(finding.verdict);
  const unsupported = finding.verdict === "unsupported";
  return (
    <li
      className="flex gap-3 rounded-md border bg-surface-2 p-3"
      style={{ borderColor: `${s.border}55` }}
    >
      {/* verdict glyph tile */}
      <span
        className="mt-0.5 inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-[5px]"
        style={{ background: s.bg, color: s.fg }}
      >
        <VerdictGlyph glyph={s.glyph} size={14} />
      </span>

      <div className="flex min-w-0 flex-col gap-1.5">
        <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
          <span className="font-mono text-[10px] uppercase tracking-[0.1em] text-fg-faint">
            §{finding.clause_ref}
          </span>
          <span
            className="font-display text-[9.5px] font-bold uppercase tracking-[0.1em]"
            style={{ color: s.fg }}
          >
            {finding.verdict}
          </span>
          <span className="tnum font-mono text-[10px] text-fg-faint">
            {(finding.confidence * 100).toFixed(0)}% conf
          </span>
        </div>

        <p className="font-mono text-[12px] leading-[1.6] text-fg">
          {finding.claim}
        </p>

        {/* the evidence — or the dramatic "no matching text" for fabrications */}
        {unsupported || !finding.evidence_quote ? (
          <p className="font-mono text-[11px] italic leading-[1.55] text-danger/90">
            — no matching text in your document —
          </p>
        ) : (
          <p
            className="rounded-[4px] px-2 py-1 font-mono text-[11px] leading-[1.55] text-fg-muted"
            style={{ background: s.highlight }}
          >
            “{finding.evidence_quote}”
          </p>
        )}
      </div>
    </li>
  );
}
