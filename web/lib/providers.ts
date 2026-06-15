/**
 * Frontend-only provider data layer for the agent arena visualization.
 *
 * The backend runs each agent on an OpenAI-compatible backend across three
 * providers (see `src/agent_exchange/core/backend.py`): the AI/ML API gateway
 * (`aimlapi`, a multi-model gateway), Featherless (`featherless`, open-weight
 * models), and OpenAI. So agents genuinely run on different models/providers.
 *
 * Each demo agent below is assigned a REAL model id that these gateways serve,
 * to illustrate the cross-provider routing. The per-agent assignment is
 * illustrative (canned demo) — hence `PROVIDER_NOTE`, surfaced as a legend.
 *
 * This module does NOT touch the SSE event contract (`lib/events.ts`,
 * `lib/runState.ts`, `lib/mockRun.ts`). It is a pure lookup layer keyed off the
 * worker id / handle that the existing events already carry.
 *
 * Logo components come from `@lobehub/icons`. We use the `.Avatar` compound
 * variant: a brand-colored rounded badge that reads well as a small mark on a
 * dark node. (`.Color` is not present on every brand — e.g. OpenAI/Anthropic
 * are monochrome — whereas `.Avatar` is available on all brands we use.)
 */

import type { ComponentType, SVGProps } from "react";
import type { Framework } from "@/lib/events";
import {
  Anthropic,
  DeepSeek,
  Gemini,
  Meta,
  Mistral,
  OpenAI,
  Qwen,
} from "@lobehub/icons";

/** The mono mark accepts the full svg prop surface plus `size`. */
type LobeIconProps = SVGProps<SVGSVGElement> & { size?: string | number };

/**
 * The `.Avatar` variant is a div-based badge whose only prop we rely on is
 * `size`. Each brand's Avatar adds brand-specific props (e.g. OpenAI's `type`
 * enum), so we narrow to the common, always-present `size`.
 */
type LobeAvatarProps = { size: number };

/**
 * Structural type for a @lobehub/icons compound brand icon. Each brand exports
 * its own `CompoundedIcon` (OpenAI carries `colorGpt4`, others differ), so we
 * type only the parts we consume: callable as a mono mark, plus `.Avatar`.
 */
type BrandIcon = ComponentType<LobeIconProps> & {
  Avatar: ComponentType<LobeAvatarProps>;
};

/** Short gateway label (the router the backend calls the model through). */
export type Gateway = "AI/ML API" | "Featherless" | "OpenAI";

export interface ProviderRecord {
  /** Stable worker key as it appears in bid/hire events (e.g. "liability"). */
  key: string;
  /** Pool handle as it appears in the pool/room events (e.g. "@liability-hawk"). */
  handle: string;
  /** Human label for the agent (e.g. "Liability Hawk"). */
  label: string;
  /** A real model id the assigned gateway serves (illustrative assignment). */
  model: string;
  /** The model's brand provider (used to pick the logo), e.g. "OpenAI". */
  provider: string;
  /** Human-facing provider label (may differ from `provider`), e.g. "Meta (Llama)". */
  providerLabel: string;
  /** The gateway/router the backend reaches the model through. */
  gateway: Gateway;
  /** The @lobehub/icons compound icon for this brand. */
  brand: BrandIcon;
}

/**
 * The six demo agents. Six DISTINCT brand logos around the ring read instantly
 * as "cross-provider". Models are real ids the named gateway serves; the
 * per-agent assignment is illustrative for the canned demo.
 */
export const PROVIDERS: ProviderRecord[] = [
  {
    // CrewAI framework brain, open-weight on Featherless (matches the live CrewAISpecialist).
    key: "liability",
    handle: "@liability-hawk",
    label: "Liability Hawk",
    model: "Qwen2.5-72B-Instruct",
    provider: "Qwen",
    providerLabel: "Qwen",
    gateway: "Featherless",
    brand: Qwen,
  },
  {
    // LangGraph framework brain, frontier on AI/ML API (matches the live LangGraphSpecialist).
    key: "ip",
    handle: "@ip-warden",
    label: "IP Warden",
    model: "claude-haiku-4.5",
    provider: "Anthropic",
    providerLabel: "Anthropic (Claude)",
    gateway: "AI/ML API",
    brand: Anthropic,
  },
  {
    // CrewAI framework brain, open-weight on Featherless — the SECOND Featherless
    // model (distinct from liability's Qwen) so the open-weight side shows model
    // variety. Matches the live secondary CrewAI slot (FEATHERLESS_MODEL_2).
    key: "termination",
    handle: "@clause-clerk",
    label: "Clause Clerk",
    model: "Mistral-Small-24B-Instruct-2501",
    provider: "Mistral",
    providerLabel: "Mistral",
    gateway: "Featherless",
    brand: Mistral,
  },
  {
    key: "data_privacy",
    handle: "@privacy-sentinel",
    label: "Privacy Sentinel",
    model: "Llama-3.3-70B-Instruct",
    provider: "Meta",
    providerLabel: "Meta (Llama)",
    gateway: "Featherless",
    brand: Meta,
  },
  {
    key: "indemnity",
    handle: "@indemnity-owl",
    label: "Indemnity Owl",
    model: "DeepSeek-V3",
    provider: "DeepSeek",
    providerLabel: "DeepSeek",
    gateway: "Featherless",
    brand: DeepSeek,
  },
  {
    key: "tax",
    handle: "@tax-scribe",
    label: "Tax Scribe",
    model: "Gemini-2.0-Flash",
    provider: "Google",
    providerLabel: "Google (Gemini)",
    gateway: "AI/ML API",
    brand: Gemini,
  },
];

/**
 * Fallback record for an unknown agent (e.g. the seeded probe). Must be COHERENT:
 * Featherless and AI/ML API are *alternative* gateways, so the brand can't be the
 * Featherless logo while routing through AI/ML API — that reads as two gateways at
 * once. Instead this mirrors the backend's real default — Claude (claude-haiku-4.5)
 * served through the AI/ML API multi-model gateway (see AIMLAPI_MODEL) — so the
 * disc brand and the gateway chip agree on a single router.
 */
export const FALLBACK_PROVIDER: ProviderRecord = {
  key: "",
  handle: "",
  label: "Agent",
  model: "claude-haiku-4.5",
  provider: "Anthropic",
  providerLabel: "Claude",
  gateway: "AI/ML API",
  brand: Anthropic,
};

function normalize(input: string): string {
  return input.trim().toLowerCase().replace(/^@/, "");
}

/**
 * Resolution records for the SIM / replay scenarios (`server/sim.py`), which use
 * different agent identities than the canned `mockRun` demo. The contract-audit
 * specialties (`liability`/`ip`/`termination`/`tax`) already match `PROVIDERS`
 * keys, so their EVENT side resolves — only their pool handles (`liability-bot`,
 * …) need aliasing. The NDA specialties aren't in `PROVIDERS` at all, so they get
 * their own records here, indexed by BOTH their worker key and their pool handle.
 *
 * These are deliberately NOT added to `PROVIDERS` (which seeds the pre-pool
 * "waiting ring"); they only extend resolution so a replay's nodes get a logo and
 * their node-key matches the event worker-key (so edges activate). Without this,
 * a sim pool handle resolves to FALLBACK and node-key ≠ event-key → dead edges.
 */
const SIM_NDA_RECORDS: ProviderRecord[] = [
  {
    key: "confidentiality_scope",
    handle: "confidentiality-bot",
    label: "Confidentiality Auditor",
    model: "gpt-4o-mini",
    provider: "OpenAI",
    providerLabel: "OpenAI",
    gateway: "AI/ML API",
    brand: OpenAI,
  },
  {
    key: "permitted_use",
    handle: "permitted-use-bot",
    label: "Permitted-Use Auditor",
    model: "Qwen2.5-72B-Instruct",
    provider: "Qwen",
    providerLabel: "Qwen",
    gateway: "Featherless",
    brand: Qwen,
  },
  {
    // The NDA secondary CrewAI/Featherless slot — distinct from permitted_use's
    // Qwen, mirroring contract-audit's two-Featherless-model pairing.
    key: "term_survival",
    handle: "term-bot",
    label: "Term & Survival Auditor",
    model: "Mistral-Small-24B-Instruct-2501",
    provider: "Mistral",
    providerLabel: "Mistral",
    gateway: "Featherless",
    brand: Mistral,
  },
  {
    key: "carve_outs",
    handle: "carveout-bot",
    label: "Carve-out Auditor",
    model: "Gemini-2.0-Flash",
    provider: "Google",
    providerLabel: "Google (Gemini)",
    gateway: "AI/ML API",
    brand: Gemini,
  },
];

/** Sim contract-audit pool handles → the existing `PROVIDERS` key they map to. */
const SIM_HANDLE_ALIASES: Record<string, string> = {
  "liability-bot": "liability",
  "ip-bot": "ip",
  "termination-bot": "termination",
  "tax-bot": "tax",
};

// Pre-built lookup: every record indexed by its normalized worker key AND handle,
// plus the sim/replay aliases above so a recorded run resolves the same as the
// canned demo.
const INDEX: Map<string, ProviderRecord> = (() => {
  const m = new Map<string, ProviderRecord>();
  for (const rec of [...PROVIDERS, ...SIM_NDA_RECORDS]) {
    m.set(normalize(rec.key), rec);
    m.set(normalize(rec.handle), rec);
  }
  for (const [alias, key] of Object.entries(SIM_HANDLE_ALIASES)) {
    const rec = m.get(normalize(key));
    if (rec) m.set(normalize(alias), rec);
  }
  return m;
})();

/**
 * Resolve a provider record by worker key OR handle, case- and `@`-insensitive.
 * Bid/hire events carry the `worker` key; pool/room events carry the `handle` —
 * this matches both. Unknown agents get `FALLBACK_PROVIDER`.
 */
export function resolveProvider(workerOrHandle: string): ProviderRecord {
  if (!workerOrHandle) return FALLBACK_PROVIDER;
  return INDEX.get(normalize(workerOrHandle)) ?? FALLBACK_PROVIDER;
}

/**
 * The @lobehub/icons component to render for a record. Returns the brand's
 * `.Avatar` compound variant — a brand-colored rounded badge that reads as a
 * small mark on a dark node.
 */
export function logoFor(record: ProviderRecord): ComponentType<LobeAvatarProps> {
  return record.brand.Avatar;
}

/**
 * Gateway router brands. @lobehub/icons ships a real `Featherless` logo, but it
 * has no "AI/ML API" mark, so gateways are exposed as short text labels the
 * arena renders as small text chips. Keep these stable for chip styling.
 */
export const GATEWAYS: Record<Gateway, { label: string }> = {
  "AI/ML API": { label: "AI/ML API" },
  Featherless: { label: "Featherless" },
  OpenAI: { label: "OpenAI" },
};

/**
 * Agent FRAMEWORKS — the agent-orchestration framework an agent runs on, which is
 * ORTHOGONAL to its model provider/gateway (a LangGraph agent still runs ON
 * AI/ML API). Surfacing this is the "3 frameworks collaborating in one Band room"
 * story. No @lobehub mark exists for these, so the arena renders them as small
 * text chips. `accent` is a CSS custom-property token (reused from the existing
 * palette) so a non-native framework reads at a glance; `native` carries no
 * accent (it's the unlabeled / muted default). Keep stable for chip styling.
 */
export const FRAMEWORKS: Record<
  Framework,
  { label: string; accent: string | null }
> = {
  native: { label: "native", accent: null },
  langgraph: { label: "LangGraph", accent: "var(--ax-emerald)" },
  crewai: { label: "CrewAI", accent: "var(--ax-gold)" },
};

/**
 * Sponsor brands. Neither is in @lobehub/icons, so the arena renders these as
 * text/badge chips. Exposed as named constants so styling stays consistent.
 */
export const SPONSOR_BAND = { key: "band", label: "Band" } as const;
export const SPONSOR_X402 = { key: "x402", label: "x402" } as const;

/**
 * Honesty legend caption. The per-agent model assignment is illustrative; what
 * is true is that the backend routes across these providers/gateways.
 */
export const PROVIDER_NOTE =
  "Models shown illustrate cross-provider routing via Band + AI/ML API + Featherless.";
