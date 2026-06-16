/**
 * Reduces the SSE event stream into the single view-model the dashboard renders.
 * Pure function — `applyEvent(state, ev) -> state` — so it's trivially testable
 * and the React layer just dispatches.
 */

import type {
  ApprovalEvent,
  BidEvent,
  DocumentEvent,
  DoneEvent,
  DriftEvent,
  EscalationEvent,
  ExchangeEvent,
  FindingEvent,
  HireEvent,
  PoolAgent,
  ReceiptEvent,
  RoomMessageEvent,
  SettleEvent,
  StageEvent,
} from "./events";

export interface RoomLine extends RoomMessageEvent {
  id: number;
}

export interface RunState {
  running: boolean;
  finished: boolean;
  error: string | null;

  stages: StageEvent[];
  document: DocumentEvent | null;
  pool: PoolAgent[];
  bids: BidEvent[];
  hire: HireEvent | null;
  hiredWorkers: Set<string>;
  room: RoomLine[];
  /** Raw `worker` ids that have emitted `progress {done:true}` (collaborate done). */
  collabDone: Set<string>;
  findings: FindingEvent[];
  drifts: DriftEvent[];
  /** Claims the verifier was too unsure to pass — routed to a human (needs_human). */
  escalations: EscalationEvent[];
  /** Human review verdicts on escalated claims (DEMO-only; never on the live path). */
  approvals: ApprovalEvent[];
  settlements: SettleEvent[];
  receipt: ReceiptEvent | null;
  done: DoneEvent | null;

  _roomSeq: number;
}

const STAGE_ORDER = [
  "Post",
  "Discover",
  "Bid",
  "Hire",
  "Work",
  "Verify",
  "Settle",
  "Done",
];

export function initialState(): RunState {
  return {
    running: false,
    finished: false,
    error: null,
    stages: STAGE_ORDER.map((name) => ({ name, status: "pending" as const })),
    document: null,
    pool: [],
    bids: [],
    hire: null,
    hiredWorkers: new Set(),
    room: [],
    collabDone: new Set(),
    findings: [],
    drifts: [],
    escalations: [],
    approvals: [],
    settlements: [],
    receipt: null,
    done: null,
    _roomSeq: 0,
  };
}

export function applyEvent(prev: RunState, ev: ExchangeEvent): RunState {
  switch (ev.type) {
    case "stage":
      return { ...prev, stages: upsertStage(prev.stages, ev.data) };
    case "document":
      return { ...prev, document: ev.data as DocumentEvent };
    case "pool":
      return { ...prev, pool: ev.data.agents };
    case "bid":
      return { ...prev, bids: [...prev.bids, ev.data as BidEvent] };
    case "hire": {
      const hire = ev.data as HireEvent;
      return {
        ...prev,
        hire,
        hiredWorkers: new Set(hire.hired.map((h) => h.worker)),
      };
    }
    case "room_message": {
      const line: RoomLine = { ...(ev.data as RoomMessageEvent), id: prev._roomSeq };
      return { ...prev, room: [...prev.room, line], _roomSeq: prev._roomSeq + 1 };
    }
    case "progress": {
      // Track per-worker collaborate-completion. Only `done:true` advances the
      // ring; a defensive `done:false` is a no-op (keeps any prior completion).
      if (!ev.data.done) return prev;
      const collabDone = new Set(prev.collabDone);
      collabDone.add(ev.data.worker);
      return { ...prev, collabDone };
    }
    case "finding":
      return { ...prev, findings: [...prev.findings, ev.data as FindingEvent] };
    case "drift":
      return { ...prev, drifts: [...prev.drifts, ev.data as DriftEvent] };
    case "escalate":
      return {
        ...prev,
        escalations: [...prev.escalations, ev.data as EscalationEvent],
      };
    case "approval":
      return {
        ...prev,
        approvals: [...prev.approvals, ev.data as ApprovalEvent],
      };
    case "settle":
      return { ...prev, settlements: [...prev.settlements, ev.data as SettleEvent] };
    case "receipt":
      return { ...prev, receipt: ev.data as ReceiptEvent };
    case "done":
      return { ...prev, done: ev.data as DoneEvent, running: false, finished: true };
    case "error":
      return { ...prev, error: ev.data.message, running: false };
    default:
      return prev;
  }
}

function upsertStage(stages: StageEvent[], next: StageEvent): StageEvent[] {
  const idx = stages.findIndex((s) => s.name === next.name);
  if (idx === -1) return [...stages, next];
  const copy = stages.slice();
  copy[idx] = next;
  return copy;
}

/** Map a settlement to the pool agent that did the work (best-effort by worker id). */
export function settledTotals(settlements: SettleEvent[]): {
  settled: number;
  withheld: number;
} {
  let settled = 0;
  let withheld = 0;
  for (const s of settlements) {
    settled += s.settled_usd;
    withheld += Math.max(0, s.authorized_usd - s.settled_usd);
  }
  return { settled, withheld };
}
