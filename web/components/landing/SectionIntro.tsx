import type { ReactNode } from "react";

/**
 * SectionIntro — the landing's section header. Replaces the repeated tiny
 * floating uppercase eyebrow (an AI-scaffolding tell) with an instrument-panel
 * ruled label + a confident, black display headline. One coherent treatment so
 * every section reads as a panel in the same console, not a generic stack.
 */
export function SectionIntro({
  label,
  children,
  tone = "emerald",
  className = "",
}: {
  /** Short section label, shown beside the accent rule. */
  label: string;
  /** The section headline. */
  children: ReactNode;
  tone?: "emerald" | "gold";
  className?: string;
}) {
  const accent = tone === "gold" ? "var(--ax-gold)" : "var(--ax-emerald)";
  return (
    <div className={className}>
      <span className="mb-5 inline-flex items-center gap-2.5 font-mono text-[11px] font-medium uppercase tracking-[0.16em] text-fg-muted">
        <span
          className="inline-block h-px w-7"
          style={{ background: accent, boxShadow: `0 0 8px -1px ${accent}` }}
        />
        {label}
      </span>
      <h2 className="font-display font-black leading-[1.04] tracking-[-0.02em] text-fg text-[clamp(1.9rem,3.6vw,2.85rem)]">
        {children}
      </h2>
    </div>
  );
}
