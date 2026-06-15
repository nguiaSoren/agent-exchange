/**
 * Per-node derived view-model. Folds the flat RunState event slices
 * (bids / hire / room / findings / settlements) into one record PER node key,
 * so each <ArenaNode> renders off a single object instead of re-scanning the
 * arrays. All keys are the stable provider key (see geometry.keyForRef), so a
 * bid ("liability") and a pool entry ("@liability-hawk") land on one node.
 */

import type {
  BidEvent,
  DriftEvent,
  FindingEvent,
  Framework,
  SettleEvent,
  Verdict,
} from "@/lib/events";
import type { RunState, RoomLine } from "@/lib/runState";
import { keyForRef } from "./geometry";

export type NodeStatus =
  | "idle"
  | "bidding"
  | "hired"
  | "declined"
  | "working"
  | "judged"
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
  /** The agent framework this node runs on (from pool/bid; default "native"). */
  framework: Framework;
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
  framework: "native",
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
    if (a.handle) handleToKey.set(keyForRef(a.handle), nodeKey);
  }

  for (const bid of state.bids) {
    const vm = ensure(keyForRef(bid.worker));
    vm.bid = bid;
    vm.framework = bid.framework;
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
  if (vm.findings.length > 0) return "judged";
  if (vm.hired) {
    if (currentStage === "Work") return "working";
    return "hired";
  }
  if (vm.declined) return "declined";
  if (vm.bid) return "bidding";
  return "idle";
}

export function vmFor(map: Map<string, NodeVM>, key: string): NodeVM {
  return map.get(key) ?? EMPTY_VM;
}
