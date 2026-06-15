"use client";

import { useCallback, useState } from "react";
import { LiveDot, NeonButton, Shield } from "@/components/hud";
import { SectionIntro } from "./SectionIntro";
import { scrollIntoFullView } from "@/lib/scroll";
import type { JobKind } from "@/lib/events";

/* ─────────────────────────────────────────────────────────────────────── */
/*  Run it live in a REAL Band room — the hackathon bullseye.               */
/*                                                                          */
/*  A judge picks/edits a contract (or pastes their own), clicks Run, and   */
/*  watches REAL agents discover → bid → cross-owner recruit → collaborate  */
/*  in a real Band room → verify → catch a seeded lie → $0, streamed live   */
/*  into the arena above. This DOES NOT reimplement the run: it dispatches   */
/*  `ax:run-live` and the Dashboard reuses its existing live path           */
/*  (runJob → POST /api/run SSE → the arena). When the live backend is      */
/*  busy/capped/flaky, the Dashboard transparently falls back to a RECORDED  */
/*  real run — so this section never lands the judge in a dead spinner.      */
/* ─────────────────────────────────────────────────────────────────────── */

const MAX_CHARS = 20_000;

/* Compact presets a judge can run in one click — the spirit of lib/mockRun.ts's
   docs, trimmed so the textarea reads at a glance and stays editable. */
const SAMPLE_CONTRACT = `MASTER SERVICES AGREEMENT

3. Limitation of Liability. Vendor's aggregate liability under this Agreement shall not exceed the total fees paid by Customer in the twelve (12) months preceding the event giving rise to the claim. Neither party is liable for indirect, incidental, or consequential damages.

7. Data Protection. Vendor shall process Customer Personal Data only on documented instructions and shall notify Customer of a personal-data breach without undue delay and in any event within 72 hours.

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

export function TryItLive() {
  const [kind, setKind] = useState<JobKind>("contract-audit");
  // Prefilled with a runnable sample; the judge can edit or fully replace it.
  const [text, setText] = useState<string>(SAMPLE_CONTRACT);

  // Swap the prefilled sample across kinds — but only if the textarea still
  // holds a pristine preset, so we never clobber a judge's own paste.
  const swapKind = useCallback(
    (next: JobKind) => {
      if (next === kind) return;
      setKind(next);
      setText((t) =>
        t === SAMPLE_CONTRACT || t === SAMPLE_NDA ? sampleFor(next) : t,
      );
    },
    [kind],
  );

  const fillSample = useCallback(() => setText(sampleFor(kind)), [kind]);

  // Fire the LIVE run. We DON'T reimplement the SSE/arena — we dispatch the
  // window event the Dashboard listens for (parity with ax:run-demo) and scroll
  // the judge up to the arena so the stream is in frame as it starts.
  const runLive = useCallback(() => {
    const document = text.trim();
    if (!document) return;
    window.dispatchEvent(
      new CustomEvent("ax:run-live", { detail: { kind, document } }),
    );
    const arena =
      typeof window !== "undefined"
        ? window.document.getElementById("arena-stage")
        : null;
    // Land on the arena's BOTTOM so the sponsor legend ("…routing via Band +
    // AI/ML API + Featherless") stays in frame; the ring fills upward from there.
    scrollIntoFullView(arena, { align: "bottom" });
  }, [kind, text]);

  const charCount = text.length;
  const over = charCount > MAX_CHARS;

  return (
    <section
      id="try-it-live"
      className="mx-auto max-w-6xl px-5 py-20 sm:px-8 sm:py-24"
    >
      <div className="ax-fade-up mb-12 max-w-2xl">
        <SectionIntro label="Run it live in a real Band room">
          Pick a contract. Watch real agents prove the work.
        </SectionIntro>
        <p className="mt-4 font-mono text-[13px] leading-[1.8] text-fg-muted">
          Pick a contract or write your own. Real agents — across owners — get
          discovered, recruited into a live Band room, collaborate, and the
          calibrated verifier catches a planted lie{" "}
          <span className="text-emerald">→ $0</span>. This is the actual Band
          API, not a simulation.
        </p>
      </div>

      <div className="ax-fade-up flex flex-col gap-4 rounded-lg border border-hud bg-surface p-6">
        {/* live badge row */}
        <div className="flex flex-wrap items-center justify-between gap-3">
          <span className="inline-flex items-center gap-2 font-mono text-[10px] font-medium uppercase tracking-[0.16em] text-emerald-glow">
            <LiveDot tone="emerald" size={7} />
            Live · real Band rooms · real x402 testnet
          </span>
          <span className="font-mono text-[10px] uppercase tracking-[0.12em] text-fg-faint">
            POST /api/run
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
              htmlFor="try-live-doc"
              className="font-mono text-[10px] uppercase tracking-[0.14em] text-fg-faint"
            >
              {kind === "nda-review" ? "NDA" : "Contract"} text — edit or paste
              your own
            </label>
            <button
              type="button"
              onClick={fillSample}
              className="font-mono text-[11px] text-emerald-glow underline-offset-2 outline-none transition hover:underline focus-visible:underline"
            >
              reset to sample
            </button>
          </div>
          <textarea
            id="try-live-doc"
            value={text}
            onChange={(e) => setText(e.target.value.slice(0, MAX_CHARS))}
            spellCheck={false}
            placeholder="Paste your contract or NDA here — or keep the sample and just hit Run."
            className="tnum h-56 w-full resize-y rounded-md border border-hud-neutral bg-surface-2 p-3 font-mono text-[12px] leading-[1.65] text-fg outline-none transition placeholder:text-fg-faint focus-visible:border-emerald focus-visible:ring-1 focus-visible:ring-emerald/40"
          />
          <div className="flex items-center justify-between gap-3">
            <span
              className={`tnum font-mono text-[10.5px] ${over ? "text-danger" : "text-fg-faint"}`}
            >
              {charCount.toLocaleString()} / {MAX_CHARS.toLocaleString()} chars
            </span>
            <span className="font-mono text-[10.5px] text-fg-faint">
              graded against the text you bring
            </span>
          </div>
        </div>

        <NeonButton
          type="button"
          onClick={runLive}
          disabled={charCount === 0}
          className="w-full"
        >
          <Shield size={14} />▶ Run it live
        </NeonButton>

        {/* honesty caveat — the seeded-lie disclosure */}
        <p className="mt-1 font-mono text-[11px] leading-[1.75] text-fg-faint">
          Honest by design: the run includes{" "}
          <span className="text-fg">one deliberately-planted false claim</span> —
          a seeded test, clearly distinct from the genuine findings — so you can
          watch the verifier catch it and withhold pay{" "}
          <span className="text-emerald">($0)</span>. Everything else is exactly
          what the real agents and the real verifier produce. Settlement is
          testnet (Base Sepolia).
        </p>
      </div>
    </section>
  );
}
