/**
 * Typed mirror of the backend's SSE lifecycle stream.
 *
 * The backend emits named SSE events (`event: <name>\n data: <json>\n\n`) over
 * `POST {API_BASE}/api/run`. Each event name below maps to one payload shape.
 * Keep these in lock-step with the server contract — the UI is driven entirely
 * off this union.
 */

export type StageStatus = "pending" | "active" | "done" | "error";

export type Verdict = "confirmed" | "partial" | "unsupported";

export type JobKind = "contract-audit" | "nda-review";

export type RunMode = "live" | "sim";

/** The agent FRAMEWORK an agent runs on (orthogonal to its model provider). */
export type Framework = "native" | "langgraph" | "crewai";

/** A single named stage in the job lifecycle progress indicator. */
export interface StageEvent {
  name: string;
  status: StageStatus;
}

/** The document under audit (rendered in the Verify panel). */
export interface DocumentEvent {
  kind: JobKind;
  title: string;
  document_text: string;
  budget_usd: number;
}

/** An agent advertised in the market pool. `cross_owner` = not owned by us. */
export interface PoolAgent {
  id: string;
  handle: string;
  name: string;
  owner: string;
  cross_owner: boolean;
  /** The agent framework this agent runs on (native | langgraph | crewai). */
  framework: Framework;
}

export interface PoolEvent {
  agents: PoolAgent[];
}

/** A bid placed by a worker after running its relevance probe. */
export interface BidEvent {
  worker: string;
  price_usd: number;
  relevance: number; // 0..1
  reputation: number; // 0..1 (rendered as stars)
  /** Total completed jobs backing this reputation estimate (from ReputationRecord.n_jobs).
   *  Used by the buyer-facing confidence badge: < 385 → low confidence (±5% CI not met). */
  n_jobs: number;
  /** The agent framework this worker runs on (native | langgraph | crewai). */
  framework: Framework;
}

/** The hiring decision: who got hired, who was declined, and the policy used. */
export interface HireEvent {
  hired: { worker: string; price_usd: number }[];
  declined: string[];
  strategy: string;
  pay_fraction_target: number;
}

/** A message posted into the shared work room. */
export interface RoomMessageEvent {
  sender: string;
  content: string;
}

/** One graded finding: a claim checked against the document text. */
export interface FindingEvent {
  worker: string;
  clause_ref: string;
  claim: string;
  verdict: Verdict;
  confidence: number; // 0..1
  evidence_quote?: string | null;
}

export type DriftSeverity = "info" | "warn" | "critical";

/**
 * Per-worker behavioral-drift signal, emitted once per worker inside the verify
 * flow (after `finding` events, before `settle`). `flagged=true` means a
 * behavioral anomaly was caught — the canonical case is a worker that bid a
 * frontier price but ran a cheap open-weight model (`model_switch` +
 * `price_mismatch`), surfaced as the arena's DRIFT badge.
 */
export interface DriftEvent {
  worker: string; // worker/specialty id (matches finding.worker, bid.worker)
  flagged: boolean; // true => behavioral anomaly caught
  severity: DriftSeverity;
  model: string; // the model the worker ACTUALLY ran (e.g. "gpt-4o-mini")
  baseline_label: string; // e.g. "(n=12 task)" or "(no baseline)"
  model_switch: boolean; // ran a model never seen in its baseline
  price_mismatch: boolean; // bid a frontier price for a cheap run
  overcharge_ratio: number | null; // bid/est-cost ratio (e.g. 606.1) or null
  cost_delta_pct: number | null;
  latency_delta_pct: number | null;
  summary: string; // human string, e.g. "model swap: gpt-4.1 -> gpt-4o-mini at 606.1x markup"
}

/** A settlement for one worker (USDC via x402). */
export interface SettleEvent {
  worker: string;
  pay_to: string;
  authorized_usd: number;
  settled_usd: number;
  tx_hash: string;
  status: string;
}

/** A signed receipt for the deliverable. */
export interface ReceiptEvent {
  signer: string;
  signature: string;
  deliverable_hash: string;
}

/** Terminal summary event. */
export interface DoneEvent {
  gate_passed: boolean;
  pay_fraction: number;
  total_settled_usd: number;
  total_withheld_usd: number;
  catch_summary: string;
}

export interface ErrorEvent {
  message: string;
}

/** Discriminated union of every event the UI consumes. */
export type ExchangeEvent =
  | { type: "stage"; data: StageEvent }
  | { type: "document"; data: DocumentEvent }
  | { type: "pool"; data: PoolEvent }
  | { type: "bid"; data: BidEvent }
  | { type: "hire"; data: HireEvent }
  | { type: "room_message"; data: RoomMessageEvent }
  | { type: "finding"; data: FindingEvent }
  | { type: "drift"; data: DriftEvent }
  | { type: "settle"; data: SettleEvent }
  | { type: "receipt"; data: ReceiptEvent }
  | { type: "done"; data: DoneEvent }
  | { type: "error"; data: ErrorEvent };

export type ExchangeEventType = ExchangeEvent["type"];

/** Request body for `POST /api/run`. */
export interface RunRequest {
  kind: JobKind;
  document: string;
  budget_usd: number;
  mode: RunMode;
}
