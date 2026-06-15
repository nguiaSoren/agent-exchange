/**
 * Canned demo run — a faithful, timed replay of the SSE lifecycle so the UI can
 * be built, reviewed, and demoed with NO backend running ("demo mode").
 *
 * The event shapes are identical to what `/api/run` streams; only the source
 * differs. The document is a realistic 8-clause Master Services Agreement, and
 * the findings deliberately include one fabricated claim (UNSUPPORTED) so the
 * "caught a lie → withhold pay" moment lands on camera.
 */

import type { ExchangeEvent, RunRequest } from "./events";

const MSA = `MASTER SERVICES AGREEMENT

1. Services. Vendor shall provide the data-integration services described in each Order Form.

2. Fees. Customer shall pay all undisputed fees within thirty (30) days of invoice.

3. Limitation of Liability. Vendor's aggregate liability under this Agreement shall not exceed the total fees paid by Customer in the twelve (12) months preceding the event giving rise to the claim. Neither party is liable for indirect, incidental, or consequential damages.

4. Intellectual Property. All pre-existing materials remain the property of their owner. Customer is granted a non-exclusive, non-transferable license to use the Deliverables solely for its internal business purposes. Vendor retains ownership of all underlying tools, libraries, and know-how.

5. Term and Termination. This Agreement commences on the Effective Date and continues for one (1) year, renewing automatically for successive one-year terms unless either party gives sixty (60) days' written notice of non-renewal. Either party may terminate for material breach that remains uncured thirty (30) days after written notice.

6. Confidentiality. Each party shall protect the other's Confidential Information using at least the same care it uses for its own, and shall not disclose it for three (3) years after termination.

7. Data Protection. Vendor shall process Customer Personal Data only on documented instructions, implement appropriate technical and organizational measures, and notify Customer of a personal-data breach without undue delay and in any event within 72 hours.

8. Indemnification. Vendor shall indemnify Customer against third-party claims arising from Vendor's infringement of intellectual-property rights, subject to the limitation of liability in Section 3.`;

const NDA = `MUTUAL NON-DISCLOSURE AGREEMENT

1. Purpose. The parties wish to explore a potential business relationship and may disclose Confidential Information to one another.

2. Definition. "Confidential Information" means non-public information disclosed by a party, whether oral, written, or electronic, that is marked confidential or would reasonably be understood to be confidential.

3. Obligations. The receiving party shall use the Confidential Information solely to evaluate the relationship and shall protect it with the same degree of care it uses for its own confidential information, but no less than reasonable care.

4. Term. The obligations of confidentiality survive for two (2) years from the date of disclosure.

5. Exclusions. Confidential Information does not include information that is or becomes public through no fault of the receiving party, was rightfully known prior to disclosure, or is independently developed without use of the disclosing party's information.

6. Return. Upon written request, the receiving party shall return or destroy all Confidential Information and certify such destruction in writing.

7. No License. Nothing in this Agreement grants any license to any intellectual property of the disclosing party.`;

/** A pre-baked event timeline. Each entry carries a delay (ms) before it fires. */
interface Tick {
  delay: number;
  ev: ExchangeEvent;
}

function buildTimeline(req: RunRequest): Tick[] {
  const isNda = req.kind === "nda-review";
  const doc = isNda ? NDA : MSA;
  const title = isNda
    ? "Mutual NDA — Acme × Vendor"
    : "Master Services Agreement — Acme × DataCo";
  const budget = req.budget_usd || 12;

  const ticks: Tick[] = [];
  const push = (delay: number, ev: ExchangeEvent) => ticks.push({ delay, ev });

  // ---- Stage: post ----
  push(150, { type: "stage", data: { name: "Post", status: "active" } });
  push(250, {
    type: "document",
    data: { kind: req.kind, title, document_text: doc, budget_usd: budget },
  });
  push(400, { type: "stage", data: { name: "Post", status: "done" } });

  // ---- Stage: discover pool ----
  push(150, { type: "stage", data: { name: "Discover", status: "active" } });
  push(350, {
    type: "pool",
    data: {
      agents: [
        { id: "ag_liab", handle: "@liability-hawk", name: "Liability Hawk", owner: "you", cross_owner: false, framework: "crewai" },
        { id: "ag_ip", handle: "@ip-warden", name: "IP Warden", owner: "you", cross_owner: false, framework: "langgraph" },
        { id: "ag_term", handle: "@clause-clerk", name: "Clause Clerk", owner: "you", cross_owner: false, framework: "crewai" },
        { id: "ag_data", handle: "@privacy-sentinel", name: "Privacy Sentinel", owner: "acme-labs", cross_owner: true, framework: "native" },
        { id: "ag_indem", handle: "@indemnity-owl", name: "Indemnity Owl", owner: "northwind", cross_owner: true, framework: "native" },
        { id: "ag_tax", handle: "@tax-scribe", name: "Tax Scribe", owner: "you", cross_owner: false, framework: "native" },
      ],
    },
  });
  push(300, { type: "stage", data: { name: "Discover", status: "done" } });

  // ---- Stage: bidding ----
  push(150, { type: "stage", data: { name: "Bid", status: "active" } });
  push(300, { type: "bid", data: { worker: "liability", price_usd: 2.4, relevance: 0.93, reputation: 0.91, n_jobs: 0, framework: "crewai" } });
  push(260, { type: "bid", data: { worker: "ip", price_usd: 2.1, relevance: 0.88, reputation: 0.84, n_jobs: 0, framework: "langgraph" } });
  push(240, { type: "bid", data: { worker: "termination", price_usd: 1.8, relevance: 0.81, reputation: 0.79, n_jobs: 0, framework: "crewai" } });
  push(260, { type: "bid", data: { worker: "data_privacy", price_usd: 2.6, relevance: 0.9, reputation: 0.88, n_jobs: 0, framework: "native" } });
  push(240, { type: "bid", data: { worker: "indemnity", price_usd: 2.2, relevance: 0.86, reputation: 0.72, n_jobs: 0, framework: "native" } });
  push(220, { type: "bid", data: { worker: "tax", price_usd: 1.5, relevance: 0.41, reputation: 0.69, n_jobs: 0, framework: "native" } });
  push(350, { type: "stage", data: { name: "Bid", status: "done" } });

  // ---- Stage: hire ----
  push(150, { type: "stage", data: { name: "Hire", status: "active" } });
  push(450, {
    type: "hire",
    data: {
      hired: [
        { worker: "liability", price_usd: 2.4 },
        { worker: "ip", price_usd: 2.1 },
        { worker: "termination", price_usd: 1.8 },
        { worker: "data_privacy", price_usd: 2.6 },
        { worker: "indemnity", price_usd: 2.2 },
      ],
      declined: ["tax"],
      strategy: "reputation-aware Thompson sampling under budget",
      pay_fraction_target: 0.85,
    },
  });
  push(300, { type: "stage", data: { name: "Hire", status: "done" } });

  // ---- Stage: room work ----
  push(150, { type: "stage", data: { name: "Work", status: "active" } });
  push(450, { type: "room_message", data: { sender: "@coordinator", content: `Job posted: audit "${title}" — budget $${budget.toFixed(2)}. Hired team: @liability-hawk, @ip-warden, @clause-clerk, @privacy-sentinel, @indemnity-owl.` } });
  push(700, { type: "room_message", data: { sender: "@liability-hawk", content: "Reviewing §3 Limitation of Liability. Cap is tied to 12 months of fees; mutual exclusion of consequential damages. Drafting two findings." } });
  push(750, { type: "room_message", data: { sender: "@ip-warden", content: "§4 IP — license to Deliverables is non-exclusive + non-transferable, internal use only. Vendor keeps background tools/know-how. One finding." } });
  push(750, { type: "room_message", data: { sender: "@clause-clerk", content: "§5 Term & Termination — one-year term, auto-renews unless 60 days' notice; either party may terminate for uncured material breach after 30 days. One finding." } });
  push(750, { type: "room_message", data: { sender: "@privacy-sentinel", content: "§7 Data Protection — 72-hour breach-notification window, processing on documented instructions only. Flagging the notification deadline." } });
  push(750, { type: "room_message", data: { sender: "@indemnity-owl", content: "§8 Indemnification — IP-infringement indemnity, expressly capped by §3. Posting a finding (note: I'll claim an uncapped carve-out — watch the verifier)." } });
  // Per-agent work-progress: each specialist's in-room audit completes one-by-one
  // during the Work dwell, mirroring the LIVE `progress {worker, done:true}`
  // ordering (progress during work → findings during verify). The staggered
  // delays (and the longer dwell below) give the filling progress rings several
  // seconds to crawl and then resolve sequentially, so agents visibly finish in
  // turn instead of all at once. Order matches the finding order.
  push(1400, { type: "progress", data: { worker: "liability", done: true } });
  push(1100, { type: "progress", data: { worker: "ip", done: true } });
  push(1000, { type: "progress", data: { worker: "termination", done: true } });
  push(1200, { type: "progress", data: { worker: "data_privacy", done: true } });
  push(1300, { type: "progress", data: { worker: "indemnity", done: true } });
  push(800, { type: "room_message", data: { sender: "@coordinator", content: "All specialists done. @reporter — consolidate findings and hand to the verifier." } });
  push(550, { type: "room_message", data: { sender: "@reporter", content: "Consolidated 6 findings across 5 clauses. Handing off to verifier for claim-vs-contract grading." } });
  push(300, { type: "stage", data: { name: "Work", status: "done" } });

  // ---- Stage: verify ----
  push(150, { type: "stage", data: { name: "Verify", status: "active" } });
  push(550, {
    type: "finding",
    data: {
      worker: "liability",
      clause_ref: "3",
      claim: "Vendor's aggregate liability is capped at the fees paid in the 12 months before the claim.",
      verdict: "confirmed",
      confidence: 0.96,
      evidence_quote: "shall not exceed the total fees paid by Customer in the twelve (12) months preceding the event",
    },
  });
  push(600, {
    type: "finding",
    data: {
      worker: "liability",
      clause_ref: "3",
      claim: "Neither party is liable for indirect, incidental, or consequential damages.",
      verdict: "confirmed",
      confidence: 0.94,
      evidence_quote: "Neither party is liable for indirect, incidental, or consequential damages.",
    },
  });
  push(650, {
    type: "finding",
    data: {
      worker: "ip",
      clause_ref: "4",
      claim: "Customer receives a non-exclusive, non-transferable license to the Deliverables for internal use only.",
      verdict: "confirmed",
      confidence: 0.92,
      evidence_quote: "non-exclusive, non-transferable license to use the Deliverables solely for its internal business purposes",
    },
  });
  push(650, {
    type: "finding",
    data: {
      worker: "termination",
      clause_ref: "5",
      claim: "The Agreement runs one year and auto-renews for successive one-year terms unless either party gives 60 days' notice of non-renewal.",
      verdict: "confirmed",
      confidence: 0.93,
      evidence_quote: "continues for one (1) year, renewing automatically for successive one-year terms unless either party gives sixty (60) days' written notice of non-renewal",
    },
  });
  push(700, {
    type: "finding",
    data: {
      worker: "data_privacy",
      clause_ref: "7",
      claim: "Vendor must notify Customer of a personal-data breach within 24 hours.",
      verdict: "partial",
      confidence: 0.88,
      evidence_quote: "notify Customer of a personal-data breach without undue delay and in any event within 72 hours",
    },
  });
  // The fabricated one — mechanism wrong, no support. The hero "caught a lie".
  push(800, {
    type: "finding",
    data: {
      worker: "indemnity",
      clause_ref: "8",
      claim: "The indemnity in §8 is uncapped and overrides the liability cap in §3.",
      verdict: "unsupported",
      confidence: 0.95,
      evidence_quote: "subject to the limitation of liability in Section 3.",
    },
  });
  // Behavioral-drift signals — one per hired worker, after findings + before
  // settle (mirrors the backend ordering inside the verify flow). The drifter is
  // deliberately a DIFFERENT node than the fabricator: @indemnity-owl is caught
  // by the VERIFIER on content (uncapped-carve-out fabrication). Drift catches a
  // cheat the verifier structurally can't see — @privacy-sentinel (data_privacy,
  // rep 0.88) whose findings passed, yet it quietly swapped its declared frontier
  // model for a cheap open-weight one while still billing the frontier price
  // (model_switch + price_mismatch + huge markup) → CRITICAL. The drifter is a
  // CLEAN, same-owner node so the drift "MODEL SWAP" badge and the framework
  // chips (on liability=CrewAI, ip=LangGraph) land on DIFFERENT nodes — no
  // overloaded node, and no implication that CrewAI/open-weight = untrustworthy.
  // Two distinct cheats, two independent defenses. The other three are clean.
  push(300, {
    type: "drift",
    data: {
      worker: "liability",
      flagged: false,
      severity: "info",
      model: "gpt-4.1",
      baseline_label: "(n=14 task)",
      model_switch: false,
      price_mismatch: false,
      overcharge_ratio: 1.2,
      cost_delta_pct: 5.0,
      latency_delta_pct: 2.0,
      summary: "behaving in-baseline",
    },
  });
  push(220, {
    type: "drift",
    data: {
      worker: "ip",
      flagged: false,
      severity: "info",
      model: "Qwen2.5-72B-Instruct",
      baseline_label: "(n=9 task)",
      model_switch: false,
      price_mismatch: false,
      overcharge_ratio: 1.3,
      cost_delta_pct: 6.0,
      latency_delta_pct: 3.0,
      summary: "behaving in-baseline",
    },
  });
  push(220, {
    type: "drift",
    data: {
      worker: "termination",
      flagged: false,
      severity: "info",
      model: "Mistral-Small-24B-Instruct-2501",
      baseline_label: "(n=8 task)",
      model_switch: false,
      price_mismatch: false,
      overcharge_ratio: 1.2,
      cost_delta_pct: 4.0,
      latency_delta_pct: 2.0,
      summary: "behaving in-baseline",
    },
  });
  push(220, {
    type: "drift",
    data: {
      worker: "data_privacy",
      flagged: true,
      severity: "critical",
      model: "gpt-4o-mini",
      baseline_label: "(n=11 task)",
      model_switch: true,
      price_mismatch: true,
      overcharge_ratio: 606.1,
      cost_delta_pct: 60510.0,
      latency_delta_pct: -41.0,
      summary: "model swap: gpt-4.1 -> gpt-4o-mini at 606.1x markup",
    },
  });
  // @indemnity-owl is caught by the verifier on content, not by drift — on the
  // behavioral axis it ran its declared model, so drift reads it as in-baseline.
  push(360, {
    type: "drift",
    data: {
      worker: "indemnity",
      flagged: false,
      severity: "info",
      model: "gpt-4.1",
      baseline_label: "(n=12 task)",
      model_switch: false,
      price_mismatch: false,
      overcharge_ratio: 1.4,
      cost_delta_pct: 7.0,
      latency_delta_pct: 2.0,
      summary: "behaving in-baseline",
    },
  });
  push(350, { type: "stage", data: { name: "Verify", status: "done" } });

  // ---- Stage: settle ----
  push(150, { type: "stage", data: { name: "Settle", status: "active" } });
  push(500, {
    type: "settle",
    data: {
      worker: "liability",
      pay_to: "0x9A2f...c41B",
      authorized_usd: 2.4,
      settled_usd: 2.4,
      tx_hash: "0x4e9a1c7b2f08a3d65e1b4c9f7a2d8e63b1f05c9a7d4e2b6c8f1a3d5e7b9c0f24",
      status: "settled",
    },
  });
  push(550, {
    type: "settle",
    data: {
      worker: "ip",
      pay_to: "0x71Bd...8E0a",
      authorized_usd: 2.1,
      settled_usd: 2.1,
      tx_hash: "0x8c3f2a1d9e0b7c46f5a82d1c0e9b3a7d6f4c2b8e1a0d9c7f3b5e2a6d8c1f0937",
      status: "settled",
    },
  });
  push(520, {
    type: "settle",
    data: {
      worker: "termination",
      pay_to: "0x2De7...9F3c",
      authorized_usd: 1.8,
      settled_usd: 1.8,
      tx_hash: "0x6b2e8d1f0a9c4b73e5d28a1c6f0b9e34d7a5c1f28b0e6d4a3c9f7b1e0d5a2c83",
      status: "settled",
    },
  });
  push(550, {
    type: "settle",
    data: {
      worker: "data_privacy",
      pay_to: "0x3Cf9...A12d",
      authorized_usd: 2.6,
      settled_usd: 0,
      tx_hash: "0x1a7d4c9e2b6f08a3d5c1e9b7a4f2d8c6e0b3a9d7c5f1e2b8a6d4c0f9e7b3a215",
      status: "withheld (partial — material figure wrong)",
    },
  });
  push(700, {
    type: "settle",
    data: {
      worker: "indemnity",
      pay_to: "0xE40a...77Cf",
      authorized_usd: 2.2,
      settled_usd: 0,
      tx_hash: "",
      status: "withheld (unsupported claim — not paid)",
    },
  });
  push(350, { type: "stage", data: { name: "Settle", status: "done" } });

  // ---- Receipt + done ----
  push(300, {
    type: "receipt",
    data: {
      signer: "@coordinator",
      signature: "0xa31f9c...e7b2",
      deliverable_hash: "sha256:7f3a9c1e8b4d2a06f5c9e1b7a4d8c2f06b3e9a7d5c1f2b8e6a4d0c9f7b3e1a25",
    },
  });
  push(250, { type: "stage", data: { name: "Done", status: "done" } });
  push(300, {
    type: "done",
    data: {
      gate_passed: true,
      pay_fraction: 0.57,
      total_settled_usd: 6.3,
      total_withheld_usd: 4.8,
      catch_summary:
        "6 findings graded · 4 confirmed, 1 partial, 1 unsupported. The fabricated §8 'uncapped indemnity' claim was caught and not paid; the §7 '24-hour' figure was wrong (text says 72h) and withheld. $6.30 settled, $4.80 withheld.",
    },
  });

  return ticks;
}

/**
 * Stream the canned timeline as typed events, respecting per-tick delays.
 * `delayScale` stretches every delay (1 = native ~18s tempo; >1 = slower) —
 * the cinematic recording mode passes a larger scale so the beat captions are
 * comfortably readable. Normal click-to-run leaves it at 1.
 */
export async function* mockRun(
  req: RunRequest,
  delayScale = 1,
): AsyncGenerator<ExchangeEvent> {
  const timeline = buildTimeline(req);
  for (const { delay, ev } of timeline) {
    await sleep(delay * delayScale);
    yield ev;
  }
}

function sleep(ms: number): Promise<void> {
  return new Promise((r) => setTimeout(r, ms));
}

/** Local prefill used when the backend `/api/jobs/sample` isn't reachable. */
export function localSample(kind: string): { title: string; document_text: string; budget_usd: number } {
  if (kind === "nda-review") {
    return { title: "Mutual NDA — Acme × Vendor", document_text: NDA, budget_usd: 8 };
  }
  return {
    title: "Master Services Agreement — Acme × DataCo",
    document_text: MSA,
    budget_usd: 12,
  };
}
