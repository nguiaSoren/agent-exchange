"use client";

/**
 * DetailDrawer — the click-to-expand detail surface for the agent arena.
 *
 * The arena gives quick HOVER cards (NodeHoverCard); this is their FULL
 * counterpart, opened by a CLICK. It recovers the depth the old result panels
 * had:
 *
 *   - kind: "agent" → everything ONE agent did this run (bid, room messages,
 *     findings with evidence, settlement + tx).
 *   - kind: "core"  → the full run / verification breakdown (the job document,
 *     ALL verdicts, the gate + settlement summary). This is what clicking the
 *     center JOB+VERIFIER core opens — the old VerifyPanel + SettleBar depth.
 *
 * Slides in from the right over a dimmed backdrop. Closes on X / backdrop /
 * Escape. Honors prefers-reduced-motion (snaps, no slide), traps + restores
 * focus, and locks body scroll while open. Built entirely on the documented
 * semantic tokens + hud primitives, so it reads correctly on both the dark HUD
 * and the white `.ax-light` surface.
 */

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { ProviderLogo } from "@/components/ProviderLogo";
import { Eyebrow, Stars, SegmentBar, CountUp, VerdictGlyph, Cross } from "@/components/hud";
import { verdictStyle, usd } from "@/lib/ui";
import { GATEWAYS, resolveProvider, PROVIDER_NOTE } from "@/lib/providers";
import type { ProviderRecord } from "@/lib/providers";
import type { RunState, RoomLine } from "@/lib/runState";
import type {
  BidEvent,
  DocumentEvent,
  DoneEvent,
  FindingEvent,
  SettleEvent,
} from "@/lib/events";
import { buildNodes, indexByKey, keyForRef, type ArenaNode } from "./geometry";
import { buildNodeVMs, vmFor, type NodeVM } from "./selectors";

/** What the arena tells the drawer to show. `null` = closed. */
export type ArenaSelection =
  | { kind: "agent"; key: string } // key = the stable provider key from resolveProvider(...).key
  | { kind: "core" }
  | null;

const TX_BASE = "https://sepolia.basescan.org/tx/";

/** Detect reduced-motion once on mount (client-only). */
function usePrefersReducedMotion(): boolean {
  const [reduced, setReduced] = useState(false);
  useEffect(() => {
    if (typeof window === "undefined" || !window.matchMedia) return;
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    setReduced(mq.matches);
    const onChange = () => setReduced(mq.matches);
    mq.addEventListener?.("change", onChange);
    return () => mq.removeEventListener?.("change", onChange);
  }, []);
  return reduced;
}

export function DetailDrawer({
  selection,
  state,
  onClose,
}: {
  selection: ArenaSelection;
  state: RunState;
  onClose: () => void;
}): JSX.Element | null {
  const reduced = usePrefersReducedMotion();
  const panelRef = useRef<HTMLDivElement | null>(null);
  const restoreFocusRef = useRef<HTMLElement | null>(null);

  // Keep the drawer mounted briefly after `selection` clears so it can animate
  // out. `open` drives the visible (slid-in) state; `mounted` drives presence.
  const [mounted, setMounted] = useState<boolean>(selection != null);
  const [open, setOpen] = useState<boolean>(false);
  // The selection we render — held through the exit animation so content
  // doesn't vanish mid-slide-out.
  const [shown, setShown] = useState<ArenaSelection>(selection);

  useEffect(() => {
    if (selection != null) {
      setShown(selection);
      setMounted(true);
      if (reduced) {
        setOpen(true);
      } else {
        // Next frame so the enter transition has a "from" state to animate off.
        const r = requestAnimationFrame(() => setOpen(true));
        return () => cancelAnimationFrame(r);
      }
    } else if (mounted) {
      setOpen(false);
      if (reduced) {
        setMounted(false);
      } else {
        const t = window.setTimeout(() => setMounted(false), 280);
        return () => window.clearTimeout(t);
      }
    }
  }, [selection, reduced, mounted]);

  // Escape to close.
  useEffect(() => {
    if (selection == null) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.stopPropagation();
        onClose();
      }
    };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [selection, onClose]);

  // Body scroll-lock while open.
  useEffect(() => {
    if (selection == null) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = prev;
    };
  }, [selection]);

  // Focus management: move focus in on open, restore on close.
  useEffect(() => {
    if (selection != null) {
      restoreFocusRef.current =
        (document.activeElement as HTMLElement | null) ?? null;
      // Defer to after the panel mounts.
      const r = requestAnimationFrame(() => {
        panelRef.current?.focus();
      });
      return () => cancelAnimationFrame(r);
    }
    // On close, restore focus to the trigger.
    const el = restoreFocusRef.current;
    if (el && typeof el.focus === "function") {
      el.focus();
    }
    restoreFocusRef.current = null;
  }, [selection]);

  // Simple focus trap: keep Tab within the panel.
  const onKeyDownTrap = useCallback((e: React.KeyboardEvent<HTMLDivElement>) => {
    if (e.key !== "Tab") return;
    const root = panelRef.current;
    if (!root) return;
    const focusables = root.querySelectorAll<HTMLElement>(
      'a[href], button:not([disabled]), textarea, input, select, [tabindex]:not([tabindex="-1"])',
    );
    if (focusables.length === 0) {
      e.preventDefault();
      root.focus();
      return;
    }
    const first = focusables[0];
    const last = focusables[focusables.length - 1];
    const active = document.activeElement;
    if (e.shiftKey) {
      if (active === first || active === root) {
        e.preventDefault();
        last.focus();
      }
    } else if (active === last) {
      e.preventDefault();
      first.focus();
    }
  }, []);

  // Resolve the per-agent / core view models off the SAME folds the arena uses.
  const nodes = useMemo(() => buildNodes(state), [state]);
  const nodeIndex = useMemo(() => indexByKey(nodes), [nodes]);
  const vms = useMemo(() => buildNodeVMs(state), [state]);

  if (!mounted || shown == null) return null;

  const labelId = "ax-drawer-title";
  const transition = reduced
    ? "none"
    : "transform 280ms cubic-bezier(0.16,1,0.3,1), opacity 280ms cubic-bezier(0.16,1,0.3,1)";

  return (
    <div
      className="fixed inset-0 z-[120] flex justify-end"
      aria-hidden={false}
    >
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-canvas/70"
        style={{
          opacity: open ? 1 : 0,
          transition: reduced ? "none" : "opacity 280ms ease",
        }}
        onClick={onClose}
        aria-hidden
      />

      {/* Panel */}
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={labelId}
        tabIndex={-1}
        onKeyDown={onKeyDownTrap}
        className="ax-scroll relative h-full w-[min(94vw,500px)] overflow-y-auto border-l border-hud-neutral bg-surface shadow-glow-emerald outline-none"
        style={{
          transform: open ? "translateX(0)" : "translateX(100%)",
          opacity: open ? 1 : 0,
          transition,
          willChange: "transform, opacity",
        }}
      >
        <CloseButton onClose={onClose} />
        {shown.kind === "agent" ? (
          <AgentView
            agentKey={shown.key}
            node={nodeIndex.get(shown.key) ?? null}
            vm={vmFor(vms, shown.key)}
            messages={state.room.filter((l) => keyForRef(l.sender) === shown.key)}
            labelId={labelId}
          />
        ) : (
          <CoreView state={state} labelId={labelId} />
        )}
      </div>
    </div>
  );
}

/* ─────────────────────────── Close button ─────────────────────────── */

function CloseButton({ onClose }: { onClose: () => void }) {
  return (
    <button
      type="button"
      onClick={onClose}
      aria-label="Close detail panel"
      className="ax-press absolute right-3 top-3 z-10 inline-flex h-8 w-8 items-center justify-center rounded-md border border-hud-neutral bg-surface-2 text-fg-muted outline-none transition hover:border-hud hover:text-fg focus-visible:ring-2 focus-visible:ring-emerald/70"
    >
      <Cross size={16} />
    </button>
  );
}

/* ─────────────────────────── Section frame ────────────────────────── */

function Section({
  eyebrow,
  children,
  className = "",
}: {
  eyebrow: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`border-t border-hud-neutral px-5 py-4 ${className}`}>
      <Eyebrow className="mb-3">{eyebrow}</Eyebrow>
      {children}
    </section>
  );
}

function EmptyLine({ children }: { children: ReactNode }) {
  return (
    <p className="font-mono text-[11px] leading-relaxed text-fg-faint">
      {children}
    </p>
  );
}

/** Render text with @mentions highlighted emerald. */
function MentionText({ text }: { text: string }) {
  const parts = text.split(/(@[a-z0-9_-]+)/gi);
  return (
    <>
      {parts.map((part, i) =>
        /^@[a-z0-9_-]+$/i.test(part) ? (
          <span key={i} className="font-medium text-emerald">
            {part}
          </span>
        ) : (
          <span key={i}>{part}</span>
        ),
      )}
    </>
  );
}

/* ─────────────────────────── Verdict chip ─────────────────────────── */

function VerdictChip({ verdict }: { verdict: FindingEvent["verdict"] }) {
  const v = verdictStyle(verdict);
  const label = v.label === "Fake" ? "Fabricated" : v.label;
  const isFake = verdict === "unsupported";
  return (
    <span
      className="inline-flex items-center gap-1 rounded-sm px-1.5 py-0.5 font-mono text-[10px] font-medium uppercase tracking-[0.08em]"
      style={{
        color: v.fg,
        background: v.bg,
        border: `1px solid ${v.border}`,
      }}
    >
      <VerdictGlyph glyph={v.glyph} size={12} />
      <span className={isFake ? "ax-glitch-live" : ""}>{label}</span>
    </span>
  );
}

/** One finding row — clause, claim, verdict chip, confidence, evidence. */
function FindingCard({ f }: { f: FindingEvent }) {
  const v = verdictStyle(f.verdict);
  const isFake = f.verdict === "unsupported";
  const tone: "emerald" | "gold" | "red" =
    f.verdict === "confirmed" ? "emerald" : f.verdict === "partial" ? "gold" : "red";
  return (
    <div
      className={`rounded-md border bg-surface-2 p-3 ${isFake ? "ax-card-red" : ""}`}
      style={{
        borderColor: isFake ? v.border : "rgb(var(--ax-border-neutral-rgb) / 1)",
      }}
    >
      <div className="flex items-start justify-between gap-2">
        <span className="font-mono text-[11px] tabular-nums text-fg">
          §{f.clause_ref}
        </span>
        <VerdictChip verdict={f.verdict} />
      </div>
      <p className="mt-1.5 text-[12px] leading-relaxed text-fg">{f.claim}</p>
      <div className="mt-2 flex items-center gap-2">
        <span className="shrink-0 font-mono text-[9px] uppercase tracking-[0.16em] text-fg-faint">
          conf
        </span>
        <SegmentBar value={f.confidence} tone={tone} variant="smooth" className="flex-1" />
        <span className="shrink-0 font-mono text-[10px] tabular-nums text-fg-muted">
          {(f.confidence * 100).toFixed(0)}%
        </span>
      </div>
      {f.evidence_quote ? (
        <blockquote
          className="mt-2 rounded-sm border-l-2 px-2.5 py-1.5 text-[11px] italic leading-relaxed text-fg-muted"
          style={{ borderColor: v.border, background: v.highlight }}
        >
          “{f.evidence_quote}”
        </blockquote>
      ) : (
        <p className="mt-2 font-mono text-[10px] text-fg-faint">
          no evidence quote{isFake ? " — claim unsupported by the document" : ""}
        </p>
      )}
    </div>
  );
}

/** Settlement readout — authorized vs settled, status, tx link. */
function SettlementBlock({ s }: { s: SettleEvent }) {
  const paid = s.settled_usd > 0;
  const withheld = Math.max(0, s.authorized_usd - s.settled_usd);
  return (
    <div className="space-y-2 font-mono text-[11px]">
      <div className="flex items-center justify-between">
        <span className="text-fg-muted">authorized</span>
        <span className="tabular-nums text-fg">{usd(s.authorized_usd)}</span>
      </div>
      <div className="flex items-center justify-between">
        <span className="text-fg-muted">settled</span>
        <span className={`tabular-nums ${paid ? "text-emerald" : "text-danger"}`}>
          {paid ? `+${usd(s.settled_usd)}` : "$0 · WITHHELD"}
        </span>
      </div>
      {withheld > 0 && (
        <div className="flex items-center justify-between">
          <span className="text-fg-muted">withheld</span>
          <span className="tabular-nums text-danger">−{usd(withheld)}</span>
        </div>
      )}
      <div className="flex items-center justify-between">
        <span className="text-fg-muted">status</span>
        <span className={`uppercase tracking-[0.08em] ${paid ? "text-fg" : "text-danger"}`}>
          {s.status}
        </span>
      </div>
      {s.tx_hash ? (
        <a
          href={`${TX_BASE}${s.tx_hash}`}
          target="_blank"
          rel="noreferrer"
          className="mt-1 block truncate text-[10px] text-emerald underline decoration-dotted underline-offset-2 outline-none focus-visible:ring-2 focus-visible:ring-emerald/70"
        >
          {s.tx_hash.slice(0, 18)}… · x402 · Base Sepolia (testnet)
        </a>
      ) : (
        !paid && (
          <p className="text-[10px] text-fg-faint">
            no on-chain settlement — payment withheld at the gate
          </p>
        )
      )}
    </div>
  );
}

/* ─────────────────────────── Agent view ───────────────────────────── */

function AgentView({
  agentKey,
  node,
  vm,
  messages,
  labelId,
}: {
  agentKey: string;
  node: ArenaNode | null;
  vm: NodeVM;
  /** Every room line this agent sent, in order (the VM only keeps the latest). */
  messages: RoomLine[];
  labelId: string;
}) {
  // Fall back to a resolved provider record if the node roster doesn't carry
  // this key yet (e.g. selection arrives before the pool).
  const provider: ProviderRecord = node?.provider ?? resolveProvider(agentKey);
  const label = node?.label ?? provider.label;
  const handle = node?.handle ?? provider.handle;
  const crossOwner = node?.crossOwner ?? false;
  const owner = node?.owner ?? null;
  const bid: BidEvent | null = vm.bid;

  return (
    <div className="pb-8">
      {/* Header */}
      <header className="px-5 pb-4 pr-12 pt-5">
        <Eyebrow className="mb-2">Agent detail</Eyebrow>
        <div className="flex items-start gap-3">
          <ProviderLogo provider={provider} size={36} />
          <div className="min-w-0 flex-1">
            <h2
              id={labelId}
              className="font-display text-[16px] font-bold uppercase tracking-[0.04em] text-fg"
            >
              {label}
            </h2>
            <div className="mt-0.5 font-mono text-[11px] text-fg-muted">{handle}</div>
            <div className="mt-2 flex flex-wrap items-center gap-2">
              <span
                className={`rounded-sm px-1.5 py-0.5 font-mono text-[9px] uppercase tracking-[0.12em] ${
                  crossOwner
                    ? "bg-gold-dim text-gold"
                    : "bg-emerald-dim text-emerald"
                }`}
              >
                {crossOwner
                  ? `cross-owner${owner ? ` · ${owner}` : ""}`
                  : "you own this"}
              </span>
              {bid && <Stars value={bid.reputation} size={13} />}
            </div>
          </div>
        </div>
        <p className="mt-3 font-mono text-[10px] leading-relaxed text-fg-muted">
          {provider.model} · {provider.providerLabel} · via{" "}
          {GATEWAYS[provider.gateway].label}
        </p>
      </header>

      {/* Bid */}
      <Section eyebrow="Bid">
        {bid ? (
          <div className="space-y-3">
            <div className="flex items-center justify-between font-mono text-[12px]">
              <span className="text-fg-muted">price</span>
              <span className="tabular-nums text-gold">{usd(bid.price_usd)}</span>
            </div>
            <div>
              <div className="mb-1 flex items-center justify-between font-mono text-[10px]">
                <span className="text-fg-muted">relevance</span>
                <span className="tabular-nums text-fg-muted">
                  {(bid.relevance * 100).toFixed(0)}%
                </span>
              </div>
              <SegmentBar value={bid.relevance} tone="emerald" segments={12} />
            </div>
            <div className="flex items-center justify-between font-mono text-[10px]">
              <span className="text-fg-muted">reputation at bid</span>
              <Stars value={bid.reputation} size={12} />
            </div>
            {vm.hired && (
              <div className="flex items-center justify-between font-mono text-[10px]">
                <span className="text-fg-muted">hired at</span>
                <span className="tabular-nums text-emerald">
                  {vm.hiredPrice != null ? usd(vm.hiredPrice) : usd(bid.price_usd)}
                </span>
              </div>
            )}
          </div>
        ) : (
          <EmptyLine>
            {vm.declined
              ? "Bid placed but not hired."
              : "Did not bid / not hired this run."}
          </EmptyLine>
        )}
      </Section>

      {/* In the room */}
      <Section eyebrow={`In the room${messages.length ? ` · ${messages.length}` : ""}`}>
        {messages.length > 0 ? (
          <ul className="space-y-2.5">
            {messages.map((m, i) => (
              <li
                key={i}
                className="rounded-md border border-hud-neutral bg-surface-2 px-3 py-2 text-[12px] leading-relaxed text-fg"
              >
                <MentionText text={m.content} />
              </li>
            ))}
          </ul>
        ) : (
          <EmptyLine>This agent posted nothing in the work room.</EmptyLine>
        )}
      </Section>

      {/* Findings */}
      <Section eyebrow={`Findings${vm.findings.length ? ` · ${vm.findings.length}` : ""}`}>
        {vm.findings.length > 0 ? (
          <div className="space-y-2.5">
            {vm.findings.map((f, i) => (
              <FindingCard key={i} f={f} />
            ))}
          </div>
        ) : (
          <EmptyLine>This agent produced no graded findings.</EmptyLine>
        )}
      </Section>

      {/* Settlement */}
      <Section eyebrow="Settlement">
        {vm.settlement ? (
          <SettlementBlock s={vm.settlement} />
        ) : (
          <EmptyLine>Not settled — no payment authorized for this agent.</EmptyLine>
        )}
      </Section>
    </div>
  );
}

/* ─────────────────────────── Core view ────────────────────────────── */

function CoreView({ state, labelId }: { state: RunState; labelId: string }) {
  const doc: DocumentEvent | null = state.document;
  const findings = state.findings;
  const settlements = state.settlements;
  const done: DoneEvent | null = state.done;

  const isIdle =
    !doc && findings.length === 0 && settlements.length === 0 && done == null;

  if (isIdle) {
    return (
      <div className="pb-8">
        <header className="px-5 pb-4 pr-12 pt-5">
          <Eyebrow className="mb-2">Verification core</Eyebrow>
          <h2
            id={labelId}
            className="font-display text-[16px] font-bold uppercase tracking-[0.04em] text-fg"
          >
            The job & verifier
          </h2>
        </header>
        <Section eyebrow="No run yet">
          <EmptyLine>Run the demo to see the document, verdicts, and settlement.</EmptyLine>
        </Section>
      </div>
    );
  }

  const tally = countVerdicts(findings);

  return (
    <div className="pb-8">
      {/* Header — the job */}
      <header className="px-5 pb-4 pr-12 pt-5">
        <Eyebrow className="mb-2">Verification core</Eyebrow>
        <h2
          id={labelId}
          className="font-display text-[16px] font-bold uppercase tracking-[0.04em] text-fg"
        >
          {doc?.title ?? "The job & verifier"}
        </h2>
        {doc && (
          <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 font-mono text-[10px]">
            <span className="uppercase tracking-[0.12em] text-fg-muted">{doc.kind}</span>
            <span className="text-fg-muted">
              budget{" "}
              <span className="tabular-nums text-gold">{usd(doc.budget_usd)}</span>
            </span>
          </div>
        )}
      </header>

      {/* The document */}
      <Section eyebrow="The document">
        {doc?.document_text ? (
          <pre className="ax-scroll max-h-64 overflow-y-auto whitespace-pre-wrap rounded-md border border-hud-neutral bg-surface-2 p-3 font-mono text-[11px] leading-relaxed text-fg-muted">
            {doc.document_text}
          </pre>
        ) : (
          <EmptyLine>Document text not available.</EmptyLine>
        )}
      </Section>

      {/* Verdicts */}
      <Section
        eyebrow={`Verdicts${findings.length ? ` · ${findings.length}` : ""}`}
      >
        {findings.length > 0 ? (
          <>
            <p className="mb-3 font-mono text-[10px] text-fg-muted">
              <span className="tabular-nums text-fg">{tally.total}</span> graded ·{" "}
              <span className="tabular-nums text-emerald">{tally.confirmed}</span> confirmed,{" "}
              <span className="tabular-nums text-gold">{tally.partial}</span> partial,{" "}
              <span className="tabular-nums text-danger">{tally.unsupported}</span> fabricated
            </p>
            <div className="space-y-2.5">
              {findings.map((f, i) => (
                <CoreFindingCard key={i} f={f} />
              ))}
            </div>
          </>
        ) : (
          <EmptyLine>No verdicts graded yet.</EmptyLine>
        )}
      </Section>

      {/* The gate / settlement summary */}
      <Section eyebrow="The gate">
        {done ? (
          <div className="space-y-3.5">
            <div className="flex items-center justify-between">
              <span className="font-mono text-[11px] text-fg-muted">gate</span>
              <span
                className={`rounded-sm px-2 py-0.5 font-display text-[11px] font-bold uppercase tracking-[0.1em] ${
                  done.gate_passed
                    ? "bg-emerald-dim text-emerald"
                    : "bg-danger-dim text-danger"
                }`}
              >
                {done.gate_passed ? "Passed" : "Failed"}
              </span>
            </div>

            <div>
              <div className="mb-1 flex items-center justify-between font-mono text-[10px]">
                <span className="text-fg-muted">pay fraction</span>
                <span className="tabular-nums text-fg-muted">
                  {(done.pay_fraction * 100).toFixed(0)}%
                </span>
              </div>
              <SegmentBar
                value={done.pay_fraction}
                tone={done.gate_passed ? "emerald" : "gold"}
                segments={12}
              />
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div className="rounded-md border border-hud-neutral bg-surface-2 p-3">
                <div className="font-mono text-[9px] uppercase tracking-[0.16em] text-fg-faint">
                  settled
                </div>
                <CountUp
                  value={done.total_settled_usd}
                  prefix="$"
                  decimals={2}
                  className="mt-1 block font-display text-[18px] font-bold text-emerald"
                />
              </div>
              <div className="rounded-md border border-hud-neutral bg-surface-2 p-3">
                <div className="font-mono text-[9px] uppercase tracking-[0.16em] text-fg-faint">
                  withheld
                </div>
                <CountUp
                  value={done.total_withheld_usd}
                  prefix="$"
                  decimals={2}
                  className="mt-1 block font-display text-[18px] font-bold text-danger"
                />
              </div>
            </div>

            {done.catch_summary && (
              <p className="rounded-md border border-hud-neutral bg-surface-2 px-3 py-2 text-[11px] leading-relaxed text-fg-muted">
                {done.catch_summary}
              </p>
            )}
          </div>
        ) : (
          <EmptyLine>The run hasn’t reached the settlement gate yet.</EmptyLine>
        )}
      </Section>

      {/* Settlements list */}
      <Section eyebrow={`Settlements${settlements.length ? ` · ${settlements.length}` : ""}`}>
        {settlements.length > 0 ? (
          <ul className="space-y-2">
            {settlements.map((s, i) => (
              <SettlementRow key={i} s={s} />
            ))}
          </ul>
        ) : (
          <EmptyLine>No settlements recorded.</EmptyLine>
        )}
      </Section>

      {/* Footer caption */}
      <p className="px-5 pt-3 font-mono text-[9px] leading-relaxed text-fg-faint">
        {PROVIDER_NOTE}
      </p>
    </div>
  );
}

/** A finding in the core view — prefixes the worker (with logo). */
function CoreFindingCard({ f }: { f: FindingEvent }) {
  const provider = resolveProvider(f.worker);
  return (
    <div className="space-y-1.5">
      <div className="flex items-center gap-1.5">
        <ProviderLogo provider={provider} size={16} />
        <span className="font-mono text-[10px] text-fg-muted">{provider.label}</span>
      </div>
      <FindingCard f={f} />
    </div>
  );
}

/** One settlement line in the core list. */
function SettlementRow({ s }: { s: SettleEvent }) {
  const provider = resolveProvider(s.worker);
  const paid = s.settled_usd > 0;
  return (
    <li className="flex items-center justify-between gap-2 rounded-md border border-hud-neutral bg-surface-2 px-3 py-2">
      <div className="flex min-w-0 items-center gap-2">
        <ProviderLogo provider={provider} size={18} />
        <div className="min-w-0">
          <div className="truncate font-mono text-[11px] text-fg">{provider.label}</div>
          {s.tx_hash ? (
            <a
              href={`${TX_BASE}${s.tx_hash}`}
              target="_blank"
              rel="noreferrer"
              className="block truncate font-mono text-[9px] text-emerald underline decoration-dotted underline-offset-2 outline-none focus-visible:ring-2 focus-visible:ring-emerald/70"
            >
              {s.tx_hash.slice(0, 14)}… · x402
            </a>
          ) : (
            <div className="truncate font-mono text-[9px] uppercase tracking-[0.08em] text-fg-faint">
              {s.status}
            </div>
          )}
        </div>
      </div>
      <span
        className={`shrink-0 font-mono text-[12px] tabular-nums ${
          paid ? "text-emerald" : "text-danger"
        }`}
      >
        {paid ? `+${usd(s.settled_usd)}` : "$0 · WITHHELD"}
      </span>
    </li>
  );
}

/* ─────────────────────────── helpers ──────────────────────────────── */

function countVerdicts(findings: FindingEvent[]): {
  total: number;
  confirmed: number;
  partial: number;
  unsupported: number;
} {
  let confirmed = 0;
  let partial = 0;
  let unsupported = 0;
  for (const f of findings) {
    if (f.verdict === "confirmed") confirmed++;
    else if (f.verdict === "partial") partial++;
    else unsupported++;
  }
  return { total: findings.length, confirmed, partial, unsupported };
}
