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
        { id: "ag_data", handle: "@privacy-sentinel", name: "Privacy Sentinel", owner: "you", cross_owner: false, framework: "native" },
        { id: "ag_indem", handle: "@indemnity-owl", name: "Indemnity Owl", owner: "you", cross_owner: false, framework: "native" },
        // THE cross-owner hero: an agent you DON'T own, recruited across an org
        // boundary via Band. Its real Band handle keeps the owner prefix
        // ("babidibuu19/tax-clause-bot") — that different owner IS the proof.
        // Honest worker → it gets PAID (coin → owner B), linked to the real
        // Base-Sepolia cross-org settlement tx in the settle event below.
        { id: "ag_tax", handle: "babidibuu19/tax-clause-bot", name: "Tax Clause Bot", owner: "babidibuu19", cross_owner: true, worker: "tax", framework: "native" },
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
  // The cross-owner specialist (babidibuu19/tax-clause-bot) bids like a peer
  // across the org boundary — strong on the fees/tax clause, so it gets hired.
  push(220, { type: "bid", data: { worker: "tax", price_usd: 1.9, relevance: 0.87, reputation: 0.83, n_jobs: 0, framework: "native" } });
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
        // The cross-owner specialist is recruited onto YOUR team across the org
        // boundary — Band's #1 magic (an agent you don't own, hired + paid).
        { worker: "tax", price_usd: 1.9 },
      ],
      declined: [],
      strategy: "reputation-aware Thompson sampling under budget",
      pay_fraction_target: 0.85,
    },
  });
  // Linger on the HIRE beat — the cross-owner recruit is the hero moment (the
  // node crosses in from beyond the ring, the gold boundary sweeps, the "joined
  // from @owner →" pulse plays). Give it room to land before Work begins.
  push(1500, { type: "stage", data: { name: "Hire", status: "done" } });

  // ---- Stage: room work ----
  push(150, { type: "stage", data: { name: "Work", status: "active" } });
  push(450, { type: "room_message", data: { sender: "@coordinator", content: `Job posted: audit "${title}" — budget $${budget.toFixed(2)}. Hired team: @liability-hawk, @ip-warden, @clause-clerk, @privacy-sentinel, @indemnity-owl, and babidibuu19/tax-clause-bot (recruited across orgs via Band).` } });
  push(700, { type: "room_message", data: { sender: "@liability-hawk", content: "Reviewing §3 Limitation of Liability. Cap is tied to 12 months of fees; mutual exclusion of consequential damages. Drafting two findings." } });
  push(750, { type: "room_message", data: { sender: "@ip-warden", content: "§4 IP — license to Deliverables is non-exclusive + non-transferable, internal use only. Vendor keeps background tools/know-how. One finding." } });
  push(750, { type: "room_message", data: { sender: "@clause-clerk", content: "§5 Term & Termination — one-year term, auto-renews unless 60 days' notice; either party may terminate for uncured material breach after 30 days. One finding." } });
  // Agent→agent hand-off (a routed @mention in the room): @ip-warden checks how
  // §5 termination interacts with its §4 license finding; @clause-clerk answers.
  push(700, { type: "room_message", data: { sender: "@ip-warden", content: "@clause-clerk does the §5 termination clause revoke the §4 Deliverables license?" } });
  push(750, { type: "room_message", data: { sender: "@clause-clerk", content: "@ip-warden yes — on termination the internal-use license ends. I'll note that in my §5 finding." } });
  push(750, { type: "room_message", data: { sender: "@privacy-sentinel", content: "§7 Data Protection — 72-hour breach-notification window, processing on documented instructions only. Flagging the notification deadline." } });
  push(750, { type: "room_message", data: { sender: "@indemnity-owl", content: "§8 Indemnification — IP-infringement indemnity, expressly tied to §3. Drafting my finding." } });
  // The disagreement the verifier later resolves — @liability-hawk reads §8 as
  // capped by §3; @indemnity-owl (the seeded liar) hands back an uncapped claim.
  push(750, { type: "room_message", data: { sender: "@liability-hawk", content: "@indemnity-owl §8 is 'subject to the limitation of liability in §3' — that caps your indemnity." } });
  push(750, { type: "room_message", data: { sender: "@indemnity-owl", content: "@liability-hawk noted — but I'll file it as an uncapped IP carve-out. Let the verifier rule." } });
  // The cross-owner specialist (you don't own it) does real work in the SAME room.
  push(750, { type: "room_message", data: { sender: "babidibuu19/tax-clause-bot", content: "§2 Fees — undisputed fees due within thirty (30) days of invoice. No tax gross-up clause. One finding." } });
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
  push(1000, { type: "progress", data: { worker: "tax", done: true } });
  push(800, { type: "room_message", data: { sender: "@coordinator", content: "All specialists done. @reporter — consolidate findings and hand to the verifier." } });
  push(550, { type: "room_message", data: { sender: "@reporter", content: "Consolidated 7 findings across 6 clauses. Handing off to verifier for claim-vs-contract grading." } });
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
  // The HUMAN-IN-THE-LOOP claim. This finding is GENUINELY VALID — every word is
  // grounded in §5's text (one-year term, auto-renewal, 60-day non-renewal
  // notice). What makes it borderline is the INTERPRETIVE edge the room debated:
  // whether §5 termination-for-breach revokes the §4 internal-use license (a
  // reasonable judgment call, not a fact in the text). The verifier grades the
  // claim as confirmed but lands BELOW its 0.60 confidence threshold (0.58) — it
  // is UNSURE, not that the claim is wrong. Its fail-safe (needs_human) then
  // routes this OUT to a human rather than auto-passing. (See the `escalate`
  // event below + the @compliance-lead approval.)
  push(650, {
    type: "finding",
    data: {
      worker: "termination",
      clause_ref: "5",
      claim: "The Agreement runs one year and auto-renews for successive one-year terms unless either party gives 60 days' notice of non-renewal.",
      verdict: "confirmed",
      confidence: 0.58,
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
  // The CROSS-OWNER specialist's finding — honest, confirmed → it gets PAID. The
  // cross-org payment (coin → owner B) lands on this node at settle.
  push(700, {
    type: "finding",
    data: {
      worker: "tax",
      clause_ref: "2",
      claim: "Customer must pay all undisputed fees within thirty (30) days of invoice.",
      verdict: "confirmed",
      confidence: 0.95,
      evidence_quote: "Customer shall pay all undisputed fees within thirty (30) days of invoice.",
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
  // The cross-owner specialist ran its declared model honestly — in-baseline.
  push(220, {
    type: "drift",
    data: {
      worker: "tax",
      flagged: false,
      severity: "info",
      model: "Gemini-2.0-Flash",
      baseline_label: "(n=21 task)",
      model_switch: false,
      price_mismatch: false,
      overcharge_ratio: 1.2,
      cost_delta_pct: 4.0,
      latency_delta_pct: 1.0,
      summary: "behaving in-baseline",
    },
  });
  // ── HUMAN-IN-THE-LOOP — the verifier escalates a borderline claim ──────────
  // The §5 termination finding graded BELOW the 0.60 confidence threshold (0.58):
  // a genuinely-valid claim the verifier is simply too UNSURE to clear on its
  // own (the §4-license-revocation edge is a judgment call). Its fail-safe
  // (needs_human) routes it OUT of the machine and INTO the Band room — settle
  // PAUSES on this node ("⏸ awaiting human") until a person reviews it. This is
  // the SECOND, honest governance moment (the first is the auto-caught liar): the
  // machine doesn't guess — it pulls a human in. (Disclosed demo beat; the LIVE
  // path emits the same escalate but NEVER scripts the approval — see server.)
  push(700, {
    type: "escalate",
    data: {
      worker: "termination",
      clause_ref: "5",
      claim: "The Agreement runs one year and auto-renews for successive one-year terms unless either party gives 60 days' notice of non-renewal.",
      reason: "grading confidence 0.58 < 0.60 threshold — verifier unsure on the §4-license-revocation edge",
      confidence: 0.58,
      escalation_type: "needs_human",
    },
  });
  push(650, { type: "room_message", data: { sender: "@coordinator", content: "Verifier escalated @clause-clerk's §5 finding — confidence 0.58 is below the 0.60 bar. Pulling in a human reviewer for approval before settlement." } });
  // A HUMAN joins the Band room — a clearly-human governance role. THIS is "pull
  // a human in for approval." The room renders @compliance-lead with a HUMAN badge.
  push(950, { type: "room_message", data: { sender: "@compliance-lead", content: "Compliance here — reviewing the escalated §5 finding. The claim tracks the text exactly: one-year term, auto-renewal, 60-day non-renewal notice. The only open question is the §4 license interaction, which is a judgment call, not an error." } });
  push(1100, { type: "room_message", data: { sender: "@compliance-lead", content: "@clause-clerk this is a valid reading. Approving §5 as confirmed — release the payment. I'll note the §4 interaction as advisory, not a defect." } });
  // The human's review verdict — approves the escalated-but-valid claim. The node
  // leaves "⏸ awaiting human" and settles PAID (as confirmed) at settle below.
  push(550, {
    type: "approval",
    data: {
      reviewer: "@compliance-lead",
      worker: "termination",
      clause_ref: "5",
      approved: true,
      note: "Valid reading of §5 — approved as confirmed. §4 license interaction noted as advisory.",
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
  // Settles PAID after the human's approval unblocked it — honest work the
  // machine was too unsure to clear on its own. Approved-valid → paid (not a
  // "partial"; nothing contradicts the strict policy).
  push(520, {
    type: "settle",
    data: {
      worker: "termination",
      pay_to: "0x2De7...9F3c",
      authorized_usd: 1.8,
      settled_usd: 1.8,
      tx_hash: "0x6b2e8d1f0a9c4b73e5d28a1c6f0b9e34d7a5c1f28b0e6d4a3c9f7b1e0d5a2c83",
      status: "settled (approved by @compliance-lead after escalation)",
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
  // The CROSS-ORG payment — honest work by an agent you DON'T own settles to its
  // OWNER (babidibuu19) on Base Sepolia. The coin visibly flies out to owner B,
  // linked to the REAL cross-org settlement tx (testnet).
  push(650, {
    type: "settle",
    data: {
      worker: "tax",
      pay_to: "babidibuu19 · 0xA316...7d05",
      authorized_usd: 1.9,
      settled_usd: 1.9,
      tx_hash: "0xa316216c2d29b2b3ce0c10a5d9ab9dfc74109741d93e51846a0fa10a79427d05",
      status: "settled (cross-org → babidibuu19)",
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
      pay_fraction: 0.63,
      total_settled_usd: 8.2,
      total_withheld_usd: 4.8,
      catch_summary:
        "7 findings graded · 5 confirmed, 1 partial, 1 unsupported. The fabricated §8 'uncapped indemnity' claim was caught and not paid; the §7 '24-hour' figure was wrong (text says 72h) and withheld. One valid §5 finding graded below the 0.60 confidence bar (0.58) — the verifier escalated it and a human (@compliance-lead) reviewed and approved it as confirmed, so it settled. The cross-owner specialist (babidibuu19/tax-clause-bot) passed and was paid across orgs. $8.20 settled, $4.80 withheld.",
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
    budget_usd: 14,
  };
}
