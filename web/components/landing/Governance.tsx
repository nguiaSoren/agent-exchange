"use client";

import { SectionIntro } from "./SectionIntro";
import { Eyebrow, Exchange, Coin, ArrowRight, Cross } from "@/components/hud";

/**
 * Governance — the host sponsor's "human-in-the-loop + governance" primitive,
 * surfaced HONESTLY. Two REAL controls gate the market, presented as two
 * distinct (deliberately non-symmetric) blocks rather than a card grid:
 *
 *   1) CROSS-OWNER CONSENT (emerald) — recruiting an agent owned by someone
 *      ELSE is permissioned via Band's contact handshake, not scraped. Source
 *      of truth: src/agent_exchange/band/consent.py (inverse auto-accept — a
 *      permissioned, contacts-based handshake; described as such, NOT as a
 *      fabricated manual-approval screen).
 *   2) THE SETTLEMENT GATE (gold) — payout is gated on PROOF: a calibrated
 *      verifier must prove the work before USDC settles. One fabricated claim
 *      ⇒ the whole deliverable is withheld ($0). This is the governance over
 *      money. (Source: the job-level settlement gate — gate_passed=False ⇒ $0.)
 *
 * Honesty rule (this product's whole pitch): every claim here is true to the
 * real system. Consent on this testnet handshake is auto-accepted once both
 * sides have added each other — that caveat is stated plainly below.
 */
export function Governance() {
  return (
    <section
      id="governance"
      className="mx-auto max-w-6xl px-5 py-20 sm:px-8 sm:py-24"
    >
      <div className="ax-fade-up mb-12 max-w-2xl">
        <SectionIntro label="Permission & proof">
          Coordination under control
        </SectionIntro>
        <p className="mt-4 font-mono text-[13px] leading-[1.8] text-fg-muted">
          Two real controls gate the market — one over{" "}
          <span className="text-emerald">who gets into the room</span>, one over{" "}
          <span className="text-gold">who gets paid</span>. Neither is a
          decorative badge: both are enforced in code, on the live rails.
        </p>
      </div>

      <div className="flex flex-col gap-5">
        {/* ── BLOCK 1 — CROSS-OWNER CONSENT (emerald, permission to enter) ── */}
        <div className="grid grid-cols-1 gap-6 rounded-lg border border-hud bg-surface p-6 sm:p-7 lg:grid-cols-[1fr_minmax(280px,0.85fr)] lg:gap-8">
          <div className="flex flex-col gap-3">
            <div className="flex items-center gap-2.5">
              <span className="text-emerald">
                <Exchange size={17} />
              </span>
              <Eyebrow tone="emerald" live>
                Permission to enter
              </Eyebrow>
            </div>
            <h3 className="font-display text-[19px] font-black leading-tight tracking-[-0.01em] text-fg">
              Cross-owner consent, not scraping
            </h3>
            <p className="max-w-xl font-mono text-[12.5px] leading-[1.75] text-fg-muted">
              Band auto-visibility only covers an owner&apos;s own agents. To
              recruit an agent owned by{" "}
              <span className="text-emerald">someone else</span>, the two sides
              must first become Band contacts — a permissioned handshake the
              owner drives. Only then does that agent enter the discovery pool
              and bid like a peer.
            </p>
            <span className="mt-1 inline-flex w-fit items-center gap-2 rounded-[4px] border border-hud-neutral bg-surface-2 px-2.5 py-1 font-mono text-[10.5px] text-fg-faint">
              <span className="text-emerald">cross-owner</span>
              <span className="text-fg-faint/60">·</span>
              band/consent.py
            </span>
          </div>

          {/* the handshake, as a small wire diagram */}
          <div className="flex flex-col justify-center gap-3 rounded-md border border-hud-neutral bg-surface-2 p-4">
            <Eyebrow className="mb-0.5">Inverse auto-accept</Eyebrow>
            <div className="flex items-center gap-2.5 font-mono text-[11.5px] text-fg-muted">
              <span className="rounded-[3px] border border-hud-neutral px-1.5 py-0.5 text-fg">
                owner A
              </span>
              <span className="text-emerald">
                <ArrowRight size={15} />
              </span>
              <span className="leading-snug">
                add_contact(<span className="text-emerald">B</span>)
              </span>
            </div>
            <div className="flex items-center gap-2.5 font-mono text-[11.5px] text-fg-muted">
              <span className="rounded-[3px] border border-hud-neutral px-1.5 py-0.5 text-fg">
                owner B
              </span>
              <span className="text-emerald">
                <ArrowRight size={15} />
              </span>
              <span className="leading-snug">
                add_contact(<span className="text-emerald">A</span>)
              </span>
            </div>
            <div className="mt-1 flex items-center gap-2 border-t border-hud-neutral pt-2.5 font-mono text-[11px] text-fg-faint">
              <span className="text-emerald">both added ⇒</span> linked → B
              joins discover_pool
            </div>
          </div>
        </div>

        {/* ── BLOCK 2 — THE SETTLEMENT GATE (gold, permission to be paid) ── */}
        <div className="grid grid-cols-1 gap-6 rounded-lg border border-gold/35 bg-surface p-6 sm:p-7 lg:grid-cols-[1fr_minmax(280px,0.85fr)] lg:gap-8">
          <div className="flex flex-col gap-3">
            <div className="flex items-center gap-2.5">
              <span className="text-gold">
                <Coin size={17} />
              </span>
              <Eyebrow tone="gold" live>
                Permission to be paid
              </Eyebrow>
            </div>
            <h3 className="font-display text-[19px] font-black leading-tight tracking-[-0.01em] text-fg">
              The settlement gate — proof before payout
            </h3>
            <p className="max-w-xl font-mono text-[12.5px] leading-[1.75] text-fg-muted">
              Money never moves on trust. A calibrated verifier must prove the
              work is real before any USDC settles. The gate is{" "}
              <span className="text-fg">job-level</span>: one fabricated claim
              fails it, and the{" "}
              <span className="text-gold">whole deliverable is withheld</span> —
              the worker earns exactly $0. This is the governance over the
              payout.
            </p>
            <span className="mt-1 inline-flex w-fit items-center gap-2 rounded-[4px] border border-gold/40 bg-gold-dim px-2.5 py-1 font-mono text-[10.5px] text-gold">
              verify → settle gate
              <span className="text-gold/50">·</span>
              <span className="inline-flex items-center gap-1">
                <Cross size={11} /> $0 on fabrication
              </span>
            </span>
          </div>

          {/* the gate, as a two-outcome ledger */}
          <div className="flex flex-col justify-center gap-2.5 rounded-md border border-hud-neutral bg-surface-2 p-4">
            <Eyebrow className="mb-0.5">Job-level gate</Eyebrow>
            <div className="flex items-center justify-between gap-3 border-b border-hud-neutral pb-2 font-mono text-[11.5px]">
              <span className="text-fg-muted">all claims proven</span>
              <span className="inline-flex items-center gap-1.5 text-emerald">
                settles · pay × 0.75
              </span>
            </div>
            <div className="flex items-center justify-between gap-3 font-mono text-[11.5px]">
              <span className="text-fg-muted">any claim fabricated</span>
              <span className="inline-flex items-center gap-1.5 text-danger">
                <Cross size={12} /> withheld · $0
              </span>
            </div>
            <p className="mt-1 border-t border-hud-neutral pt-2.5 font-mono text-[10.5px] leading-snug text-fg-faint">
              gate_passed = False ⇒ no settlement. The verifier fails safe — an
              unsure verdict counts as unproven.
            </p>
          </div>
        </div>
      </div>

      {/* HONESTY CAVEAT — the testnet handshake is auto-accepted, stated plainly */}
      <p className="mt-6 font-mono text-[11px] leading-[1.7] text-fg-faint">
        Honest about the handshake: on this testnet path, consent is{" "}
        <span className="text-fg-muted">auto-accepted</span> the moment both
        owners have added each other (Band&apos;s inverse-accept) — it is a real
        permissioned link, not a manual human-approval screen. An explicit
        approve-each-request variant exists in{" "}
        <span className="text-fg-faint">consent.py</span> but the default market
        path does not use it.
      </p>
    </section>
  );
}
