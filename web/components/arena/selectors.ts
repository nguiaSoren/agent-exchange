/**
 * Per-node derived view-model. Folds the flat RunState event slices
 * (bids / hire / room / findings / settlements) into one record PER node key,
 * so each <ArenaNode> renders off a single object instead of re-scanning the
 * arrays. All keys are the stable provider key (see geometry.keyForRef), so a
 * bid ("liability") and a pool entry ("@liability-hawk") land on one node.
 */

import type {
  ApprovalEvent,
  BidEvent,
  DriftEvent,
  EscalationEvent,
  FindingEvent,
  Framework,
  SettleEvent,
  Verdict,
} from "@/lib/events";
import type { Gateway } from "@/lib/providers";
import type { RunState, RoomLine } from "@/lib/runState";
import { keyForRef } from "./geometry";

export type NodeStatus =
  | "idle"
  | "bidding"
  | "hired"
  | "declined"
  | "working"
  | "judged"
  // The verifier was too unsure (sub-threshold confidence) → routed to a human.
  // Settlement is PAUSED on this node until the human review lands.
  | "escalated"
  | "paid"
  | "withheld";

export interface NodeVM {
  bid: BidEvent | null;
  hired: boolean;
  declined: boolean;
  /** Price the node was hired at (from the hire event). */
  hiredPrice: number | null;
  /** The node's findings, in arrival order. */
  findings: FindingEvent[];
  /** Worst verdict the node earned (fake > partial > real), for node tinting. */
  worstVerdict: Verdict | null;
  /** Latest behavioral-drift signal for this node (latest wins), or null. */
  drift: DriftEvent | null;
  /** A claim of this node the verifier escalated (needs_human), or null. */
  escalation: EscalationEvent | null;
  /** The human's review verdict on this node's escalation (latest wins), or null. */
  approval: ApprovalEvent | null;
  /** True once a `progress {worker, done:true}` arrived (in-room audit complete). */
  collabDone: boolean;
  /** The agent framework this node runs on (from pool/bid; default "native"). */
  framework: Framework;
  /** The provider this node ACTUALLY routes through (LIVE pool/bid only; else undefined). */
  gateway?: Gateway;
  settlement: SettleEvent | null;
  /** Most recent room line whose sender resolves to this node. */
  lastLine: RoomLine | null;
}

const EMPTY_VM: NodeVM = {
  bid: null,
  hired: false,
  declined: false,
  hiredPrice: null,
  findings: [],
  worstVerdict: null,
  drift: null,
  escalation: null,
  approval: null,
  collabDone: false,
  framework: "native",
  gateway: undefined,
  settlement: null,
  lastLine: null,
};

const VERDICT_RANK: Record<Verdict, number> = {
  confirmed: 0,
  partial: 1,
  unsupported: 2,
};

/** Build the per-node VM map keyed by stable node key. */
export function buildNodeVMs(state: RunState): Map<string, NodeVM> {
  const map = new Map<string, NodeVM>();
  const ensure = (key: string): NodeVM => {
    let vm = map.get(key);
    if (!vm) {
      vm = { ...EMPTY_VM, findings: [] };
      map.set(key, vm);
    }
    return vm;
  };

  // Framework folds from BOTH the pool and bids (same value); the pool covers
  // nodes that never bid. Key by the specialty `worker` when present (live), else
  // the handle (sim) — matching how buildNodes keys the node. Default stays "native".
  // Also build a handle→nodeKey map so room-message senders (which arrive as Band
  // handles, e.g. "you/liability-auditor") resolve to the same node as the bids.
  const handleToKey = new Map<string, string>();
  for (const a of state.pool) {
    const nodeKey = keyForRef(a.worker || a.handle);
    ensure(nodeKey).framework = a.framework;
    if (a.gateway) ensure(nodeKey).gateway = a.gateway;
    if (a.handle) handleToKey.set(keyForRef(a.handle), nodeKey);
  }

  for (const bid of state.bids) {
    const vm = ensure(keyForRef(bid.worker));
    vm.bid = bid;
    vm.framework = bid.framework;
    if (bid.gateway) vm.gateway = bid.gateway;
  }

  if (state.hire) {
    for (const h of state.hire.hired) {
      const vm = ensure(keyForRef(h.worker));
      vm.hired = true;
      vm.hiredPrice = h.price_usd;
    }
    for (const w of state.hire.declined) ensure(keyForRef(w)).declined = true;
  }

  for (const f of state.findings) {
    const vm = ensure(keyForRef(f.worker));
    vm.findings.push(f);
    if (
      vm.worstVerdict == null ||
      VERDICT_RANK[f.verdict] > VERDICT_RANK[vm.worstVerdict]
    ) {
      vm.worstVerdict = f.verdict;
    }
  }

  // Latest drift signal per node wins (one event per worker, but be defensive).
  for (const d of state.drifts) ensure(keyForRef(d.worker)).drift = d;

  // Escalations (verifier too unsure → routed to a human) and the human's
  // review verdict, both keyed onto the node that owns the claim. Latest wins.
  for (const e of state.escalations) ensure(keyForRef(e.worker)).escalation = e;
  for (const a of state.approvals) ensure(keyForRef(a.worker)).approval = a;

  // Per-worker collaborate-completion (progress {done:true}). Keyed the same way
  // as bids/findings so the ring resolves on the node that actually finished.
  for (const w of state.collabDone) ensure(keyForRef(w)).collabDone = true;

  for (const s of state.settlements) ensure(keyForRef(s.worker)).settlement = s;

  // Latest line per node (room senders are handles; resolve to the node key —
  // via the pool's handle→key map first so LIVE handles land on the right node).
  for (const line of state.room) {
    const senderKey = keyForRef(line.sender);
    const key = handleToKey.get(senderKey) ?? senderKey;
    if (!map.has(key)) continue; // skip coordinator/reporter (non-node senders)
    map.get(key)!.lastLine = line;
  }

  return map;
}

/** The visible status for a node, used to drive its visual state. */
export function nodeStatus(vm: NodeVM, currentStage: string | null): NodeStatus {
  if (vm.settlement) {
    return vm.settlement.settled_usd > 0 ? "paid" : "withheld";
  }
  // Verifier was too unsure → a human is reviewing. Settlement PAUSES here until
  // the review lands (then a settle event flips it to paid/withheld above). The
  // human's approval doesn't itself settle — it unblocks the held claim.
  if (vm.escalation && !vm.approval) return "escalated";
  if (vm.findings.length > 0) return "judged";
  if (vm.hired) {
    // A hired node is "working" through the long thinking phase. The demo names
    // that stage "Work"; the LIVE backend names it "collaborate" (and grading is
    // "verify") — match both, case-insensitively, so the thinking animation fires
    // live too (it previously only matched the demo's "Work").
    const s = (currentStage ?? "").toLowerCase();
    if (s === "work" || s === "collaborate" || s === "verify") return "working";
    return "hired";
  }
  if (vm.declined) return "declined";
  if (vm.bid) return "bidding";
  return "idle";
}

export function vmFor(map: Map<string, NodeVM>, key: string): NodeVM {
  return map.get(key) ?? EMPTY_VM;
}
