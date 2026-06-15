/** Small presentation helpers shared across components. */

import type { Verdict } from "./events";

/** Deterministic avatar tint from a string (stable per worker/handle).
 *  Neon Arcade HUD palette: dim emerald/gold washes + desaturated green-gray
 *  fills, each paired with a bright neon ink that reads on near-black panels. */
const AVATAR_COLORS: { bg: string; fg: string }[] = [
  { bg: "rgba(0,214,122,0.18)", fg: "#2bff9a" }, // emerald
  { bg: "rgba(255,194,51,0.16)", fg: "#ffc233" }, // gold
  { bg: "rgba(43,255,154,0.10)", fg: "#7ee8b4" }, // soft emerald
  { bg: "rgba(255,213,106,0.10)", fg: "#ffd56a" }, // soft gold
  { bg: "rgba(126,157,144,0.16)", fg: "#a7c8b8" }, // green-gray
  { bg: "rgba(0,214,122,0.12)", fg: "#5fd6a0" }, // muted emerald
  { bg: "rgba(255,194,51,0.10)", fg: "#d9b873" }, // muted gold
  { bg: "rgba(82,104,94,0.22)", fg: "#8fb3a3" }, // neutral green-gray
];

export function avatarColor(seed: string): { bg: string; fg: string } {
  let h = 0;
  for (let i = 0; i < seed.length; i++) h = (h * 31 + seed.charCodeAt(i)) >>> 0;
  return AVATAR_COLORS[h % AVATAR_COLORS.length];
}

/** Initials from a worker id or handle ("data_privacy" → "DP", "@ip-warden" → "IW"). */
export function initials(name: string): string {
  const cleaned = name.replace(/^@/, "").replace(/[_-]+/g, " ").trim();
  const parts = cleaned.split(/\s+/).filter(Boolean);
  if (parts.length === 0) return "?";
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[1][0]).toUpperCase();
}

/** Title-case a worker id ("data_privacy" → "Data Privacy"). */
export function prettyWorker(id: string): string {
  return id
    .replace(/^@/, "")
    .replace(/[_-]+/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

export function usd(n: number): string {
  return `$${n.toFixed(2)}`;
}

export type Glyph = "check" | "tilde" | "cross";

export interface VerdictStyle {
  label: string;
  glyph: Glyph;
  /** neon accent (text/glyph) */
  fg: string;
  /** dim fill for chips / glyph tiles */
  bg: string;
  /** evidence-span wash inside the document */
  highlight: string;
  /** border + glow accent for the verdict's card / highlight ring */
  border: string;
}

/**
 * Neon Arcade HUD verdict semantics:
 *   confirmed   → emerald (REAL / pass)
 *   partial     → gold/amber (PARTIAL)
 *   unsupported → red (FAKE / withheld) — the one dramatic moment
 */
export function verdictStyle(v: Verdict): VerdictStyle {
  switch (v) {
    case "confirmed":
      return {
        label: "Real",
        glyph: "check",
        fg: "#2bff9a",
        bg: "rgba(0,214,122,0.18)",
        highlight: "rgba(0,214,122,0.16)",
        border: "#00d67a",
      };
    case "partial":
      return {
        label: "Partial",
        glyph: "tilde",
        fg: "#ffc233",
        bg: "rgba(255,194,51,0.18)",
        highlight: "rgba(255,194,51,0.15)",
        border: "#ffc233",
      };
    case "unsupported":
      return {
        label: "Fake",
        glyph: "cross",
        fg: "#ff3b5c",
        bg: "rgba(255,59,92,0.18)",
        highlight: "rgba(255,59,92,0.18)",
        border: "#ff3b5c",
      };
  }
}

/** Render a 0..1 reputation as a 5-star string fraction. */
export function stars(rep: number): { full: number; frac: number } {
  const scaled = Math.max(0, Math.min(1, rep)) * 5;
  return { full: Math.floor(scaled), frac: scaled - Math.floor(scaled) };
}
