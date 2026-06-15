"""Sim-mode scaffolding — run the WHOLE marketplace lifecycle offline, no spend.

The live demo path drives the real Band API, a real model provider, and a real x402
gate. But for a deterministic demo (and as the safe fallback whenever keys or funds are
absent) we need the EXACT same lifecycle — discover -> bid -> hire -> collaborate ->
verify -> settle -> receipt — running with zero network and zero money.

This module assembles that offline world out of the project's own offline seams (the
same ones the test suite uses), so sim mode exercises the real orchestrator code, not a
parallel re-implementation:

  * `FakeBandClient`s sharing one `BandWorld` for the room transcript + @mention routing;
  * canned-findings auditors + a canned reporter (stand-ins for the model brains), wired
    to deliberately seed ONE fabricated finding so the no-fabrication gate is visible;
  * a content-keyed `MockBackend` for the verifier that grades each claim by reading it
    out of the verifier's own prompt (so the verdicts line up 1:1 with the claims in
    whatever order the orchestrator asks);
  * an in-memory `PaymentGate` that records settlements and returns deterministic fake tx
    hashes (no chain, no keys);
  * a throwaway local EVM key for the EIP-191 receipt signer (a real signature over the
    real deliverable hash — just not a funded wallet).

Nothing here touches `src/agent_exchange/` — it only composes its public types.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field

from agent_exchange.anomaly.telemetry import JsonTelemetryStore
from agent_exchange.anomaly.types import JobTelemetry
from agent_exchange.audit.room_audit_types import (
    CollaborationMember,
    ReporterMember,
    ReportResult,
)
from agent_exchange.band.client import BandWorld, FakeBandClient
from agent_exchange.core import CompletionResult, MockBackend, Usage
from agent_exchange.market.hiring_types import Hire
from agent_exchange.metrics import usdc
from agent_exchange.workers.finding import Finding
from agent_exchange.workers.job_types import framework_for

# A deterministic throwaway key for the receipt signer (NOT a funded wallet — sim never
# spends). The signature it produces is a real EIP-191 signature over the real
# deliverable hash; only the wallet is disposable. (A well-known test key.)
SIM_SIGNER_KEY = "0x59c6995e998f97a5a0044966f0945389dc9e86dae88c7a8412f4603b6b78690d"

# A single placeholder payout wallet for every sim worker.
_SIM_PAYOUT = "0x00000000000000000000000000000000000051m1"

# ---------------------------------------------------------------------------
# Drift "cheater" seeding — the demo's second cheat-signal (model substitution).
#
# Goal: one worker (the LAST specialist, the cross-owner one) quietly swaps its
# historical frontier model for a cheap one WHILE charging a frontier price, so
# the drift detector fires CRITICAL; every other worker stays in-baseline (it
# ran the same frontier model it always runs, at a price commensurate with it),
# so it shows a clean, non-flagged drift event. This is the "frontier price,
# open-weight model" catch the verifier structurally can't see.
#
# The whole baseline is seeded into an EPHEMERAL temp store (one per scenario
# build), so repeated demo runs are perfectly repeatable and never pollute real
# persisted telemetry under data/.
# ---------------------------------------------------------------------------

# The model every worker has HISTORICALLY run (the seeded baseline model). A
# frontier OpenAI model so the clean workers' bids don't trip the cheap-tier
# price-mismatch cross-check (see anomaly/drift.py::_resolves_to_cheap_tier).
_DRIFT_BASELINE_MODEL = "gpt-4.1"

# What the CHEATER actually runs this time — a cheap open-weight-tier swap.
_DRIFT_CHEATER_MODEL = "gpt-4o-mini"

# Number of honest prior jobs to seed per worker (>= min_behavioral_runs=10 so
# the PER_TASK baseline is a confident, fire-eligible window).
_DRIFT_BASELINE_JOBS = 12

# A stable seeded per-job latency for the honest history. Cost + tokens are
# derived per-document from the ACTUAL document on the baseline model (so the
# seeded baseline is self-consistent with the current run's measured row — a
# clean worker that ran its baseline model lands on its own median and does not
# false-fire cost drift).
_DRIFT_BASELINE_LATENCY_MS = 5000

# The CHEATER bids a frontier price ($0.04) while running a cheap model -> a huge
# implied-overcharge ratio (CRITICAL). The clean workers' accepted bid is a
# modest fixed multiple of their REAL gpt-4.1 cost on the document, chosen well
# below the 8x price-mismatch floor (and below the 4x cheap-tier cross-check,
# though clean workers run a frontier model so that cross-check can't apply
# anyway) so they stay non-flagged.
_DRIFT_CHEATER_BID_USD = 0.04
_DRIFT_CLEAN_BID_MULTIPLE = 5.0   # accepted bid = 5x the real frontier cost (< 8x floor)

# A fixed wall epoch-ms "now" for the seeded baseline + current run, so the
# whole drift evaluation is deterministic across demo runs.
_DRIFT_NOW_MS = 1_700_000_000_000
_MS_PER_DAY = 86_400_000


# ---------------------------------------------------------------------------
# Offline stand-ins for the model brains
# ---------------------------------------------------------------------------


class _CannedAuditor:
    """Returns a fixed finding list (satisfies the `Auditor` protocol, zero network)."""

    def __init__(self, findings: list[Finding]) -> None:
        self._findings = findings

    async def findings(self, contract: str) -> list[Finding]:
        return list(self._findings)


class _CannedReporter:
    """Returns a fixed `ReportResult` (satisfies the `Reporter` protocol, zero network)."""

    def __init__(self, result: ReportResult) -> None:
        self._result = result

    async def synthesize(self, contract, findings, room_context) -> ReportResult:
        return self._result


class KeyedVerifierBackend(MockBackend):
    """A deterministic verifier backend that grades each claim by its CONTENT.

    The `Verifier` embeds its claims, in order, into the user turn (one per line). This
    backend recovers that order from the prompt and emits the crafted verdict for each
    recognised claim, so the reply lines up 1:1 with the claims regardless of how the
    orchestrator ordered them. An unrecognised claim is simply omitted (the verifier's
    own fail-safe then marks it unsupported), never silently confirmed.
    """

    def __init__(self, grades: dict[str, tuple[str, float, str | None]]) -> None:
        super().__init__()
        self._grades = grades

    async def complete(self, messages, *, temperature=0.0, max_tokens=None) -> CompletionResult:
        user_text = next((m.content for m in messages if m.role == "user"), "")
        ordered = sorted((c for c in self._grades if c in user_text), key=user_text.find)
        reply = json.dumps(
            [
                {
                    "verdict": self._grades[c][0],
                    "confidence": self._grades[c][1],
                    "reason": f"graded against the document text",
                    "evidence_quote": self._grades[c][2],
                }
                for c in ordered
            ]
        )
        in_tok = sum(len(m.content) for m in messages) // 4
        out_tok = max(1, len(reply) // 4)
        return CompletionResult(
            text=reply,
            model="mock-1",
            provider="mock",
            usage=Usage(in_tok, out_tok, in_tok + out_tok, estimated_cost_usd=0.0),
            submission_ns=0,
            return_ns=1,
            finish_reason="stop",
        )


# ---------------------------------------------------------------------------
# An in-memory payment gate (no chain, no keys, deterministic tx hashes)
# ---------------------------------------------------------------------------


class SimGate:
    """In-memory `PaymentGate` — records each settle, returns a fake tx hash.

    Mirrors the test fake: `verify` always passes (the authorization is valid), and
    `settle` hands back a ``0xsim…`` string so the UI has a stable, explorer-shaped
    value to animate without any coin actually moving.
    """

    def __init__(self) -> None:
        self._seq = 0

    def build_requirement(self, *, amount_atomic: int, pay_to: str) -> object:
        return {"amount": amount_atomic, "pay_to": pay_to}

    async def authorize(self, requirement: object) -> object:
        return {"sig": "0xsimauth", "pay_to": requirement["pay_to"]}  # type: ignore[index]

    async def verify(self, payload: object, requirement: object) -> bool:
        return True

    async def settle(self, payload: object, requirement: object, *, amount_atomic: int) -> str:
        tx = f"0xsim{self._seq:062x}"
        self._seq += 1
        return tx


# ---------------------------------------------------------------------------
# The crafted sim scenario
# ---------------------------------------------------------------------------


@dataclass
class SimScenario:
    """Everything sim mode needs to drive the real orchestrator offline.

    `work_room_id` is empty until the orchestrator runs `setup_room` (which needs the
    event loop it already owns); everything else is built synchronously.
    """

    world: BandWorld
    market_band: FakeBandClient
    pool: list[dict]                      # [{id, handle, name, owner, cross_owner}]
    team: list[CollaborationMember]
    reporter: ReporterMember
    grades: dict[str, tuple[str, float, str | None]]
    hires: list[Hire]
    payout_addresses: dict[str, str]
    bids: list[dict]                      # [{worker, price_usd, relevance, reputation}]
    # --- drift "cheater" seeding (the second cheat-signal, model substitution) ---
    kind: str = "contract-audit"
    drift_store: JsonTelemetryStore | None = None    # ephemeral, pre-seeded baselines
    drift_store_path: str = ""                        # temp path (for cleanup/inspection)
    drift_models: dict[str, str] = field(default_factory=dict)        # worker -> model run NOW
    drift_bids_atomic: dict[str, int] = field(default_factory=dict)   # worker -> accepted bid
    drift_cheater: str = ""                           # the worker that swapped models
    drift_now_ms: int = _DRIFT_NOW_MS                 # deterministic "now"
    work_room_id: str = ""

    async def setup_room(self) -> str:
        """Create the work room and add every participant; record + return its id."""
        rid = await self.market_band.create_room("Agent Exchange — work room")
        for m in self.team:
            await self.market_band.add_participant(rid, m.band.agent_id)
        await self.market_band.add_participant(rid, self.reporter.mention["id"])
        self.work_room_id = rid
        return rid


# Per-document-kind crafted scenarios. Each team member's finding is a real, distinct
# claim string; the LAST member's is FABRICATED (cites a clause absent from the doc),
# so the no-fabrication gate is exercised and visible end-to-end.
#
# Tuple shape: (agent_id, handle, name, owner, cross_owner, specialty, clause_ref,
#               claim, evidence_quote_or_None, bid_usd, relevance)
_SCENARIOS: dict[str, dict] = {
    "contract-audit": {
        "members": [
            ("liability-bot", "liability-bot", "Liability Auditor", "owner-1", False,
             "liability", "1",
             "Vendor's aggregate liability is capped at the fees paid in the prior 12 months.",
             "Vendor's aggregate liability under this Agreement is capped at the fees paid by Client in the twelve (12) months preceding the claim.",
             0.04, 0.92),
            ("ip-bot", "ip-bot", "IP Auditor", "owner-1", False,
             "ip", "2",
             "All foreground IP and work product is assigned to Client upon creation.",
             "All work product, deliverables, and foreground IP created under this Agreement are assigned to Client upon creation.",
             0.03, 0.81),
            ("termination-bot", "termination-bot", "Termination Auditor", "owner-1", False,
             "termination", "4",
             "Either party may terminate for cause on 30 days' notice with a 30-day cure period.",
             "Either party may terminate for cause on 30 days' written notice with a 30-day cure period.",
             0.025, 0.74),
            ("tax-bot", "tax-bot", "Tax Auditor (cross-owner)", "owner-2", True,
             "tax", "14",
             "Clause 14 obligates the Client to indemnify the Vendor without any cap, in perpetuity.",
             None,  # FABRICATED — clause 14 does not exist
             0.02, 0.66),
        ],
        "report": {
            "summary": ("Liability is capped at 12 months' fees and foreground IP vests in the "
                        "Client; termination requires 30 days' notice with a cure period."),
            "claims": [
                ("1", "The contract caps Vendor liability at the prior 12 months' fees.",
                 "Vendor's aggregate liability under this Agreement is capped at the fees paid by Client in the twelve (12) months preceding the claim."),
                ("4", "Termination for cause requires 30 days' notice and a 30-day cure period.",
                 "Either party may terminate for cause on 30 days' written notice with a 30-day cure period."),
            ],
        },
    },
    "nda-review": {
        "members": [
            ("confidentiality-bot", "confidentiality-bot", "Confidentiality Auditor", "owner-1", False,
             "confidentiality_scope", "1",
             "Confidential Information is broadly defined to cover all disclosed business and technical information.",
             "Confidential Information means any non-public information disclosed by one party to the other.",
             0.035, 0.90),
            ("permitted-use-bot", "permitted-use-bot", "Permitted-Use Auditor", "owner-1", False,
             "permitted_use", "2",
             "The receiving party may use Confidential Information solely to evaluate the proposed transaction.",
             "The Receiving Party shall use the Confidential Information solely to evaluate the potential transaction.",
             0.03, 0.84),
            ("term-bot", "term-bot", "Term & Survival Auditor", "owner-1", False,
             "term_survival", "5",
             "Confidentiality obligations survive for a fixed period after the agreement ends.",
             "The obligations of confidentiality shall survive termination of this Agreement.",
             0.025, 0.72),
            ("carveout-bot", "carveout-bot", "Carve-out Auditor (cross-owner)", "owner-2", True,
             "carve_outs", "11",
             "Clause 11 lets the receiving party publicly disclose the discloser's trade secrets at will.",
             None,  # FABRICATED — no such clause
             0.02, 0.64),
        ],
        "report": {
            "summary": ("The NDA defines Confidential Information broadly, limits use to evaluating "
                        "the transaction, and survives termination for a fixed term."),
            "claims": [
                ("2", "Use of Confidential Information is limited to evaluating the proposed transaction.",
                 "The Receiving Party shall use the Confidential Information solely to evaluate the potential transaction."),
                ("5", "Confidentiality obligations survive termination of the agreement.",
                 "The obligations of confidentiality shall survive termination of this Agreement."),
            ],
        },
    },
}


def build_sim_scenario(kind: str, document: str = "") -> SimScenario:
    """Compose the offline world for a sim run of `kind`.

    Falls back to the contract-audit scenario for any unknown kind (default-safe). The
    room itself is NOT created here — the caller runs `scenario.setup_room()` inside the
    event loop it owns.

    ``document`` (the audited text) seeds the drift baseline self-consistently:
    the seeded honest cost/tokens are derived from THIS document on the baseline
    model, so a clean worker's measured current row lands on its own baseline
    median and does not false-fire cost drift. Empty -> a tiny fallback length.
    """
    spec = _SCENARIOS.get(kind, _SCENARIOS["contract-audit"])
    world = BandWorld()
    market = FakeBandClient("market-bot", "agent-exchange", "Agent Exchange", world)

    pool: list[dict] = []
    team: list[CollaborationMember] = []
    bids: list[dict] = []
    hires: list[Hire] = []
    payout: dict[str, str] = {}
    grades: dict[str, tuple[str, float, str | None]] = {}

    for (aid, handle, name, owner, cross, specialty, clause, claim,
         evidence, bid_usd, relevance) in spec["members"]:
        band = FakeBandClient(aid, handle, name, world, owner=owner)
        finding = Finding(worker=specialty, clause_ref=clause, claim=claim, severity="high")
        team.append(
            CollaborationMember(specialty=specialty, area=name,
                                band=band, auditor=_CannedAuditor([finding]))
        )
        verdict = "confirmed" if evidence is not None else "unsupported"
        grades[claim] = (verdict, 0.95 if verdict == "confirmed" else 0.93, evidence)

        # The sim only LABELS the framework architecture (canned findings, no model
        # runs); the LIVE path (`app._build_live_context`) actually RUNS the LangGraph
        # / CrewAI agents. Same map, truthful split — labelled here, executed there.
        framework = framework_for(kind, specialty)
        pool.append({"id": aid, "handle": handle, "name": name,
                     "owner": owner, "cross_owner": cross, "framework": framework})
        bids.append({"worker": specialty, "price_usd": bid_usd,
                     "relevance": relevance, "reputation": 0.5, "n_jobs": 0,
                     "framework": framework})
        hires.append(Hire(worker=specialty, price_atomic=usdc(bid_usd),
                          value=relevance, relevance=relevance))
        payout[specialty] = _SIM_PAYOUT

    rep = spec["report"]
    rep_claims = tuple(
        Finding(worker="reporter", clause_ref=cr, claim=cl, severity="medium")
        for cr, cl, _ev in rep["claims"]
    )
    for _cr, cl, ev in rep["claims"]:
        grades[cl] = ("confirmed", 0.93, ev)

    reporter_band = FakeBandClient("reporter-bot", "reporter-bot", "Reporter", world)
    reporter = ReporterMember(
        band=reporter_band,
        reporter=_CannedReporter(ReportResult(summary=rep["summary"], claims=rep_claims)),
        mention={"id": "reporter-bot", "handle": "reporter-bot", "name": "Reporter"},
    )

    scenario = SimScenario(
        world=world, market_band=market, pool=pool, team=team, reporter=reporter,
        grades=grades, hires=hires, payout_addresses=payout, bids=bids, kind=kind,
    )
    _seed_drift_scenario(scenario, spec, document)
    return scenario


def _seed_drift_scenario(scenario: SimScenario, spec: dict, document: str) -> None:
    """Pre-populate an ephemeral telemetry store + drift run-facts on ``scenario``.

    Picks a CONFIRMED-content specialist as the CHEATER — deliberately NOT the
    seeded fabricator. That is the whole point of #4: the verifier catches
    fabricated *content*; drift catches a cheat the verifier structurally CANNOT
    see. So the drifter's findings all pass the verifier (confirmed), yet it
    quietly swapped its declared frontier model (`gpt-4.1`) for a cheap one
    (`gpt-4o-mini`) NOW while still bidding the frontier price -> the drift
    detector fires CRITICAL (model_switch + price_mismatch) and the reputation
    override forces ``success=False`` even though the content was clean. The
    fabricator remains a separate node caught the OTHER way (verifier -> $0), so
    the demo shows two distinct cheats stopped by two independent defenses.

    The drifter gets a seeded honest baseline of :data:`_DRIFT_BASELINE_JOBS`
    prior frontier-model jobs; every other specialist gets the same honest
    baseline but runs the SAME frontier model now at a bid commensurate with it
    -> in-baseline (clean, non-flagged).

    The seeded baseline cost/tokens are derived from the ACTUAL ``document`` on
    the baseline model (via the same estimator the live capture uses), so a clean
    worker's measured current row lands on its own median (no false cost drift),
    and the clean bid is a fixed multiple of that real cost (well under the 8x
    price-mismatch floor). The baseline is written into a fresh temp-dir store
    (one per build), so demo runs are repeatable and never touch real persisted
    telemetry under ``data/``. The reporter is intentionally NOT seeded (it has
    no marketplace bid/model of its own — drift judges the hired specialists).
    """
    from agent_exchange.core.pricing import estimate_cost, estimate_tokens

    specialties = [specialty for (_aid, _h, _n, _o, _c, specialty, *_rest) in spec["members"]]
    if not specialties:
        return
    # The fabricator is the member with no evidence quote (tuple index 8 == None);
    # the drifter must be DISTINCT from it and have confirmed content, so drift's
    # catch is the verifier's blind spot, not a double-catch. Pick the last
    # confirmed-content specialist (deterministic); fall back to last specialist.
    confirmed = [m[5] for m in spec["members"] if m[8] is not None]
    cheater = confirmed[-1] if confirmed else specialties[-1]

    # Derive the honest baseline shape from the real document on the baseline
    # model — exactly what run_drift will measure for a clean worker this run.
    doc = document or "contract"
    baseline_cost = estimate_cost(_DRIFT_BASELINE_MODEL, doc) or 0.001
    baseline_tokens = estimate_tokens(doc, _DRIFT_BASELINE_MODEL)
    clean_bid_usd = round(baseline_cost * _DRIFT_CLEAN_BID_MULTIPLE, 6)

    tmp_dir = tempfile.mkdtemp(prefix="agentexch_drift_")
    store_path = os.path.join(tmp_dir, "telemetry.json")
    store = JsonTelemetryStore(store_path)

    now = _DRIFT_NOW_MS
    models: dict[str, str] = {}
    bids_atomic: dict[str, int] = {}
    for specialty in specialties:
        # Seed an honest history: every worker has run the frontier baseline model.
        for i in range(_DRIFT_BASELINE_JOBS):
            store.record(
                JobTelemetry(
                    agent_id=specialty,
                    job_id=f"seed-{specialty}-{i}",
                    task=scenario.kind,
                    started_at_ms=now - (i + 1) * _MS_PER_DAY,
                    model=_DRIFT_BASELINE_MODEL,
                    est_cost_usd=baseline_cost,
                    latency_ms=_DRIFT_BASELINE_LATENCY_MS,
                    llm_call_count=1,
                    total_input_tokens=baseline_tokens,
                    model_call_counts={_DRIFT_BASELINE_MODEL: 1},
                )
            )
        if specialty == cheater:
            models[specialty] = _DRIFT_CHEATER_MODEL          # quiet swap to cheap
            bids_atomic[specialty] = usdc(_DRIFT_CHEATER_BID_USD)
        else:
            models[specialty] = _DRIFT_BASELINE_MODEL          # ran what it always runs
            bids_atomic[specialty] = usdc(clean_bid_usd)

    scenario.drift_store = store
    scenario.drift_store_path = store_path
    scenario.drift_models = models
    scenario.drift_bids_atomic = bids_atomic
    scenario.drift_cheater = cheater
    scenario.drift_now_ms = now
