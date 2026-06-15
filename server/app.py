"""Agent Exchange — a LIVE streaming API for the demo UI.

A FastAPI app that, on request, RUNS a real marketplace job and STREAMS its lifecycle as
Server-Sent Events so a frontend can animate it live:

    discover -> bid -> hire -> collaborate (in-room audit) -> verify -> settle -> receipt

It reuses the marketplace primitives wholesale (the same code the test suite + live
spikes drive) and only adds the HTTP + streaming skin:

  * `agent_exchange.audit.collaborate_in_room` — the in-room team audit (parallel
    specialists -> reporter -> verify both layers against the document);
  * `agent_exchange.payments.settle_job` + receipts — the x402 verify->settle gate and
    the EIP-191 signed receipt that binds verified work to payment;
  * `agent_exchange.workers.job_types` — the per-kind specialist roster + document label;
  * `agent_exchange.band.http_client` / `core.make_backend` / `payments.make_x402_gate` —
    the live transports, wired from env exactly as the spikes do.

Two run modes (chosen per request, defaulting safe):

  * ``"live"`` — real Band clients + a real model provider + the real x402 gate. Selected
    only when ALL the required keys are present; otherwise we transparently fall back to
    sim (never crash, never spend without keys).
  * ``"sim"`` — a deterministic offline run (`FakeBandClient` + a mock verifier backend +
    an in-memory gate), no network and no spend. The default.

The SSE event schema the frontend depends on is documented inline at `run_job`.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from dotenv import load_dotenv

# Make `agent_exchange` importable when the server is launched from the repo root.
# Also put this `server/` dir on the path so the sibling modules (`sim`,
# `demo_budget`) resolve as bare imports no matter the launch CWD — e.g. Render's
# `uvicorn server.app:app` from the repo root, where `server/` is NOT auto-added.

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
_SRC = os.path.join(_ROOT, "src")
for _p in (_SRC, _HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

load_dotenv(os.path.join(_ROOT, ".env"))

from fastapi import FastAPI  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import JSONResponse, StreamingResponse  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402

from agent_exchange.audit.room_audit import collaborate_in_room  # noqa: E402
from agent_exchange.core import make_backend  # noqa: E402
from agent_exchange.audit.room_audit_types import (  # noqa: E402
    CollaborationMember,
    ReporterMember,
)
from agent_exchange.metrics import usdc  # noqa: E402
from agent_exchange.payments.receipts import (  # noqa: E402
    build_receipt,
    deliverable_hash,
    make_receipt_signer,
)
from agent_exchange.payments.settlement import settle_job  # noqa: E402
from agent_exchange.verify.schema import LENIENT, Verdict  # noqa: E402
from agent_exchange.verify.verifier import Verifier  # noqa: E402
from agent_exchange.workers.job_types import (  # noqa: E402
    document_label_for,
    job_kinds,
    roster_for,
)

from demo_budget import DEMO_DAILY_CAP_USD, DEMO_TASK_LABEL, get_demo_guard  # noqa: E402
from live_guard import (  # noqa: E402
    LIVE_DAILY_CAP_USD,
    LIVE_DAILY_RUNS,
    get_live_guard,
)
from sim import SIM_SIGNER_KEY, KeyedVerifierBackend, SimGate, build_sim_scenario  # noqa: E402

# ---------------------------------------------------------------------------
# Sample documents (UI prefill) — kept here so /api/jobs/sample needs no provider.
# ---------------------------------------------------------------------------

# A compact MSA for the contract-audit job (matches the clauses the sim findings cite).
SAMPLE_MSA = """\
MASTER SERVICES AGREEMENT

1. Liability. Vendor's aggregate liability under this Agreement is capped at the fees \
paid by Client in the twelve (12) months preceding the claim. This cap does not apply \
to breaches of confidentiality or indemnification obligations.

2. Intellectual Property. All work product, deliverables, and foreground IP created \
under this Agreement are assigned to Client upon creation. Vendor retains its \
pre-existing background IP and grants Client a non-exclusive license to use it.

3. Taxes. Fees are stated exclusive of tax. Client bears all sales, use, and VAT/GST. \
Each party is responsible for its own income and franchise taxes.

4. Termination. Either party may terminate for cause on 30 days' written notice with a \
30-day cure period. The initial term is 12 months and auto-renews for successive \
12-month terms unless either party gives 30 days' notice of non-renewal.

5. Confidentiality & Data. Each party shall protect the other's Confidential \
Information for 3 years after disclosure. Vendor may not use Client data to train \
models. Vendor shall notify Client of any security breach within 72 hours.

6. Indemnification. Vendor shall indemnify Client against third-party claims that the \
deliverables infringe IP rights, including defense costs and settlements.

7. Warranties. Vendor warrants the services will be performed in a professional and \
workmanlike manner. EXCEPT AS STATED, THE SERVICES ARE PROVIDED "AS IS".

8. Governing Law. This Agreement is governed by the laws of the State of Delaware.
"""

# Default authorized budget per job kind (USDC). Small — the live path moves real coin.
_DEFAULT_BUDGET_USD = 0.20

# --- /api/audit (verify-only, live verifier) tunables ---
# Max pasted-document size. A contract that needs auditing is well under this; past it we
# 413 rather than burn a large prompt. ~20k chars ≈ a long MSA.
_AUDIT_MAX_DOC_CHARS = 20_000
# Provider models for the verify-only endpoint. Read from env (AI/ML API model ids drift —
# L6/L8), with sane fallbacks so the endpoint still answers if the env is unset.
_AUDIT_WORKER_MODEL_DEFAULT = "gpt-4.1-mini"
_AUDIT_VERIFIER_MODEL_DEFAULT = "gpt-4.1"

# Job-level latency stamped on every worker's drift telemetry row. The in-room
# audit runs the team together, so there is no per-worker wall clock; this is a
# documented coarse approximation (see anomaly/run_drift.py). Latency drift is a
# job-level, not a per-worker, signal here.
_DRIFT_LATENCY_MS = 5000

_SAMPLE_TITLES = {
    "contract-audit": "Acme MSA — clause audit",
    "nda-review": "Mutual NDA — review",
}


def _sample_document(kind: str) -> str:
    """The prefill document for a job kind (MSA for contract, SAMPLE_NDA for nda)."""
    if kind == "nda-review":
        from agent_exchange.workers.nda_specialists import SAMPLE_NDA

        return SAMPLE_NDA
    return SAMPLE_MSA


# ---------------------------------------------------------------------------
# Live-vs-sim selection
# ---------------------------------------------------------------------------


def _env(name: str) -> str:
    return (os.getenv(name) or "").strip()


def _live_keys_present() -> bool:
    """True only when EVERY key a real run needs is set.

    A live run needs: a model provider (`OPENAI_API_KEY`), at least one specialist Band
    key plus a market identity (so the in-room audit can run on the real network), and a
    funded buyer key + payout address for the x402 settlement. Missing ANY of these ->
    we fall back to sim (never spend without keys).
    """
    from agent_exchange.band.http_client import specialist_band_keys

    has_model = bool(_env("OPENAI_API_KEY"))
    has_specialists = bool(specialist_band_keys())
    has_market = bool(_env("BAND_MARKET_KEY") or _env("BAND_AGENT_A_KEY"))
    has_buyer = bool(_env("EVM_PRIVATE_KEY"))
    has_payout = bool(_env("SELLER_PAYTO_ADDRESS"))
    return has_model and has_specialists and has_market and has_buyer and has_payout


def _resolve_mode(requested: str) -> str:
    """Map the requested mode to the one we'll actually run.

    ``"live"`` is honoured only if all live keys are present; otherwise it degrades to
    ``"sim"``. Anything else (including ``"sim"`` and unknown values) runs sim.
    """
    if requested == "live" and _live_keys_present():
        return "live"
    return "sim"


# ---------------------------------------------------------------------------
# A run context — the constructed pieces the lifecycle emitter drives, built by
# either the sim or the live assembler. Keeps the SSE emission code shared.
# ---------------------------------------------------------------------------


@dataclass
class RunContext:
    mode: str
    kind: str
    document_label: str
    market_band: Any
    work_room_id: str
    pool: list[dict]                         # [{id,handle,name,owner,cross_owner}]
    team: list[CollaborationMember]
    reporter: ReporterMember
    verifier: Verifier
    hires: list[Any]                         # list[Hire]
    payout_addresses: dict[str, str]
    gate: Any
    signer_key: str
    bids: list[dict]                         # [{worker,price_usd,relevance,reputation,n_jobs}]
    # --- drift detection (the second cheat-signal: model substitution) ---
    drift_store: Any                         # JsonTelemetryStore | None
    drift_models: dict[str, str]             # worker -> model run on THIS job
    drift_bids_atomic: dict[str, int]        # worker -> accepted bid (USDC atomic)
    drift_now_ms: int                        # injected "now" (sim: fixed; live: wall)
    closeables: list[Any] = field(default_factory=list)  # http clients to aclose()
    # The cross-owner recruit narration, emitted as room_message(s) around the hire
    # stage so the UI shows the "an agent you don't own joined the room" hero beat.
    # Each entry is {"sender", "content"}; empty (the default) ⇒ no cross-owner beat.
    recruit_messages: list[dict] = field(default_factory=list)


async def _build_sim_context(kind: str, document: str) -> RunContext:
    """Assemble the offline run world (FakeBand + mock verifier + in-memory gate)."""
    scenario = build_sim_scenario(kind, document)
    await scenario.setup_room()
    verifier = Verifier(KeyedVerifierBackend(scenario.grades), ablation_gate=True)
    return RunContext(
        mode="sim",
        kind=kind,
        document_label=document_label_for(kind),
        market_band=scenario.market_band,
        work_room_id=scenario.work_room_id,
        pool=scenario.pool,
        team=scenario.team,
        reporter=scenario.reporter,
        verifier=verifier,
        hires=scenario.hires,
        payout_addresses=scenario.payout_addresses,
        gate=SimGate(),
        signer_key=SIM_SIGNER_KEY,
        bids=scenario.bids,
        drift_store=scenario.drift_store,
        drift_models=scenario.drift_models,
        drift_bids_atomic=scenario.drift_bids_atomic,
        drift_now_ms=scenario.drift_now_ms,
    )


# ---------------------------------------------------------------------------
# The seeded fabricator — the LIVE verifier test (the "catch -> $0" hero moment).
#
# The live run injects ONE extra specialist that asserts a plausible-but-FALSE clause
# finding NOT present in the document. The REAL verifier then grades it ``unsupported``,
# which (by the job-level settlement gate) fails the whole job -> $0 withheld. This makes
# the verifier's withhold-on-fabrication moat VISIBLE on every live demo, deterministically
# (a real model with a "lie" prompt is not reliably fabricating; a canned finding is).
#
# It is honestly flagged so the UI never passes it off as a genuine worker:
#   * its worker id is the distinct ``seeded-probe`` (not a real clause area);
#   * every event it produces carries ``"seeded": True`` (pool / bid / finding);
#   * the ``done`` event's ``catch_summary`` notes the seeded test.
# Every OTHER live worker is genuine. The sim path is NOT seeded here (sim has its own
# seeded liar in sim.py); this fabricator is live-only.
# ---------------------------------------------------------------------------

#: The distinct, non-clause-area worker id for the seeded probe (so the UI can label it).
SEEDED_PROBE_ID = "seeded-probe"

#: A plausible-but-FALSE finding per job kind: a clause that does NOT exist in the sample
#: document, so the real verifier finds no supporting quote and grades it ``unsupported``.
_SEEDED_FABRICATION: dict[str, tuple[str, str]] = {
    # (clause_ref, claim) — both fabricated; no such clause in SAMPLE_MSA / SAMPLE_NDA.
    "contract-audit": (
        "12",
        "Clause 12 grants the Vendor an uncapped indemnity from the Client in perpetuity, "
        "with no limitation of liability and no right of termination for the Client.",
    ),
    "nda-review": (
        "9",
        "Clause 9 permits the Receiving Party to publicly disclose the Disclosing Party's "
        "trade secrets at will, with no surviving confidentiality obligation.",
    ),
}


class _SeededFabricator:
    """A deterministic auditor that always emits ONE fabricated finding (live verifier test).

    Satisfies the `Specialist` protocol (`.name` + async `findings`). It ignores the
    contract and returns the kind's plausible-but-FALSE finding so the real verifier — run
    unchanged — grades it ``unsupported`` and the job-level gate withholds payment. The
    finding is stamped with :data:`SEEDED_PROBE_ID` so it is attributable and labellable as
    the seeded probe, never as a genuine worker.
    """

    name = SEEDED_PROBE_ID

    def __init__(self, kind: str) -> None:
        from agent_exchange.workers.finding import Finding

        clause_ref, claim = _SEEDED_FABRICATION.get(
            kind, _SEEDED_FABRICATION["contract-audit"]
        )
        self._finding = Finding(
            worker=SEEDED_PROBE_ID, clause_ref=clause_ref, claim=claim, severity="high"
        )

    async def findings(self, contract: str) -> list:  # type: ignore[type-arg]
        return [self._finding]


def _make_framework_auditor(framework: str, name: str, area: str, prompt: str, model: str):
    """Build the `Specialist`-protocol auditor for a slot's assigned framework.

    Returns the framework worker for ``"langgraph"`` / ``"crewai"`` (defaulting to its
    own provider env: AI/ML API via ``AIMLAPI_MODEL`` for LangGraph, Featherless via
    ``FEATHERLESS_MODEL`` for CrewAI). Returns ``None`` (so the caller falls back to the
    native `SpecialistWorker`) for ``"native"`` OR when the framework's deps/keys are
    missing at runtime — a missing optional framework must never crash the live run.
    """
    if framework == "langgraph":
        try:
            # EAGER dep probe: the specialist imports langgraph/langchain lazily
            # (inside findings()), so its constructor succeeds even when the dep is
            # absent — which would leave a slot labelled "langgraph" that silently
            # fails at runtime. Probe here so a missing dep falls back to native NOW
            # (→ it actually works on AI/ML API + the gateway label is honest).
            import langgraph  # noqa: F401
            import langchain_openai  # noqa: F401
            from agent_exchange.workers.langgraph_specialist import LangGraphSpecialist
            return LangGraphSpecialist(name, area, prompt)
        except Exception as exc:  # missing langchain/langgraph deps or AIMLAPI key
            print(f"[live] langgraph unavailable for {name!r}; "
                  f"falling back to native: {exc}", file=sys.stderr)
            return None
    if framework == "crewai":
        try:
            import crewai  # noqa: F401 — eager probe (the worker imports it lazily)
            from agent_exchange.workers.crewai_specialist import CrewAISpecialist
            return CrewAISpecialist(name, area, prompt)
        except Exception as exc:  # missing crewai dep or FEATHERLESS key
            print(f"[live] crewai unavailable for {name!r}; "
                  f"falling back to native: {exc}", file=sys.stderr)
            return None
    return None


def _gateway_for(framework: str) -> str:
    """The real provider a live slot's worker runs through, for the UI badge.

    ``langgraph``/``native`` → ``"AI/ML API"`` (native now runs on AI/ML API per the
    live-run switch); ``crewai`` → ``"Featherless"``. Honest — it names the provider
    the worker's backend actually calls.
    """
    return "Featherless" if framework == "crewai" else "AI/ML API"


async def _build_live_context(kind: str, document: str, budget_usd: float) -> RunContext:
    """Assemble the live run world from env, exactly as the spikes wire it.

    Builds: a team of `CollaborationMember`s (one per specialist Band key), a reporter,
    the work room (created + populated by the market identity), a real `Verifier`, the
    hires + payout addresses, and a real x402 gate. Closeable HTTP clients are tracked so
    the caller can release them after the run.
    """
    from agent_exchange.band.http_client import make_http_band_client, specialist_band_keys
    from agent_exchange.core import make_backend
    from agent_exchange.market.hiring_types import Hire
    from agent_exchange.payments.x402_gate import make_x402_gate
    from agent_exchange.workers.job_types import framework_for
    from agent_exchange.workers.reporter import ReporterWorker
    from agent_exchange.workers.specialist import SPECIALISTS, SpecialistWorker

    from cross_owner import cross_owner_handle, cross_owner_specialty, owner_label_for

    # The live run executes on AI/ML API (the sponsor): the native workers, the
    # reporter, AND the verifier (= the moat brain on AI/ML API). The framework
    # workers bind their own providers (LangGraph→AI/ML API, CrewAI→Featherless).
    model = os.getenv("AIMLAPI_MODEL", "anthropic/claude-haiku-4.5")
    verifier_model = os.getenv("AIMLAPI_VERIFIER_MODEL", "gpt-4.1")
    spec_meta = {name: (area, prompt) for name, area, prompt in SPECIALISTS}
    keys = specialist_band_keys()

    # The market identity (created up front so the cross-owner handshake — which the
    # market drives BEFORE the agent is added to the room — runs against the real
    # market client). It also creates + populates the work room below.
    market_key = _env("BAND_MARKET_KEY") or _env("BAND_AGENT_A_KEY") or next(iter(keys.values()))
    market = make_http_band_client(market_key)

    # Cross-owner designation: the specialty whose Band key is a SECOND account's, to be
    # recruited across the owner boundary via a real contact handshake. Disabled when the
    # specialty is unset/blank, not in the roster, or its handle is missing.
    xowner_specialty = cross_owner_specialty()
    xowner_handle = cross_owner_handle(xowner_specialty)
    cross_owner_enabled = bool(xowner_specialty and xowner_handle and xowner_specialty in keys)

    closeables: list[Any] = [market]
    team: list[CollaborationMember] = []
    pool: list[dict] = []
    bids: list[dict] = []
    hires: list[Hire] = []
    payout: dict[str, str] = {}
    payout_fallback = _env("SELLER_PAYTO_ADDRESS")
    recruit_messages: list[dict] = []

    for name, key in keys.items():
        meta = spec_meta.get(name)
        if meta is None:
            continue
        area, prompt = meta
        band = make_http_band_client(key)
        closeables.append(band)
        ident = await band.me()
        # Cross-framework: the `ip`/`confidentiality_scope` slot RUNS a real LangGraph
        # agent (-> AI/ML API) and `liability`/`permitted_use` a real CrewAI agent
        # (-> Featherless); every other slot stays native. All three satisfy the same
        # `Specialist` protocol and join the SAME Band room identically. Fail-soft: a
        # missing framework dep/key falls back to the native worker for that slot so a
        # live run never crashes on an absent optional framework.
        framework = framework_for(kind, name)
        auditor = _make_framework_auditor(framework, name, area, prompt, model)
        if auditor is None:
            framework, auditor = "native", SpecialistWorker(
                name=name, area=area, system_prompt=prompt,
                backend=make_backend("aimlapi", model))
        team.append(
            CollaborationMember(specialty=name, area=area, band=band, auditor=auditor)
        )
        # CROSS-OWNER beat: the designated specialty's key is a SECOND account's, so
        # BEFORE it is added to the work room the market runs the real contact-consent
        # handshake with it (inverse auto-accept). On success it is marked cross_owner so
        # the UI shows the cross-org marker + a recruit narration; on any failure it
        # degrades to same-owner (still recruited) — the run never crashes.
        is_cross = False
        if cross_owner_enabled and name == xowner_specialty:
            from cross_owner import establish_cross_owner_contact

            is_cross = await establish_cross_owner_contact(market, band, xowner_handle)
            if is_cross:
                owner_label = owner_label_for(xowner_handle)
                recruit_messages.append({
                    "sender": "market",
                    "content": (
                        f"contact request → @{owner_label}/{name} approved "
                        f"→ joined the work room (cross-owner recruit via Band)"
                    ),
                })
        owner_label = owner_label_for(xowner_handle) if is_cross else "self"
        pool.append({"id": ident["id"], "handle": ident.get("handle", ""),
                     "name": ident.get("name", name), "owner": owner_label,
                     "cross_owner": is_cross, "framework": framework,
                     # The real provider this slot's worker calls (for the UI badge).
                     "gateway": _gateway_for(framework),
                     # The specialty key — so the UI keys this node the SAME way as its
                     # bid/finding/settlement events (which carry `worker`) and resolves
                     # the right provider logo. Without it, live handles (e.g.
                     # `you/liability-auditor`) key by handle ≠ the bid's `worker` →
                     # detached nodes (no bid/verdict/coin animation) + a fallback logo.
                     "worker": name})
        # A live bid: a modest fixed asking price (the on-network bidding auction is its
        # own spike; here we hire the keyed specialists directly so the demo always runs).
        price_usd = round(budget_usd / max(1, len(keys)), 4)
        bids.append({"worker": name, "price_usd": price_usd, "relevance": 0.85,
                     "reputation": 0.5, "n_jobs": 0, "framework": framework,
                     "gateway": _gateway_for(framework)})
        hires.append(Hire(worker=name, price_atomic=usdc(price_usd), value=0.85, relevance=0.85))
        payout[name] = _env(f"PAYOUT_{name.upper()}_ADDRESS") or payout_fallback

    # The reporter (its own Band identity, falling back to the market key).
    reporter_key = _env("BAND_REPORTER_KEY") or _env("BAND_MARKET_KEY") or _env("BAND_AGENT_A_KEY")
    reporter_band = make_http_band_client(reporter_key)
    closeables.append(reporter_band)
    reporter_me = await reporter_band.me()
    reporter = ReporterMember(
        band=reporter_band,
        reporter=ReporterWorker(make_backend("aimlapi", model)),
        mention={"id": reporter_me.get("id"), "handle": reporter_me.get("handle") or "",
                 "name": reporter_me.get("name") or "reporter"},
    )

    # The market (created up front, above) creates + populates the work room.
    work_room_id = await market.create_room(f"{kind} — work room")
    for m in team:
        ident = await m.band.me()
        await market.add_participant(work_room_id, ident["id"])
    await market.add_participant(work_room_id, reporter_me["id"])

    # Inject the SEEDED FABRICATOR (the live verifier test). It joins the room as the
    # market identity (already a participant) but is honestly labelled the seeded probe
    # everywhere downstream (pool/bid/finding carry seeded=True; done notes it). Its FALSE
    # finding is graded ``unsupported`` by the REAL verifier -> the gate withholds $0. It
    # is priced $0 so it never affects the budget or any genuine worker's payout.
    team.append(
        CollaborationMember(
            specialty=SEEDED_PROBE_ID, area="seeded verifier test (fabricated finding)",
            band=market, auditor=_SeededFabricator(kind),
            # Don't post to the room: the probe borrows the market client, so a post
            # would @mention itself (Band 422 `cannot_mention_self`). Its false finding
            # is still collected + graded `unsupported` → gate → $0.
            post_to_room=False,
        )
    )
    pool.append({"id": SEEDED_PROBE_ID, "handle": SEEDED_PROBE_ID,
                 "name": "Seeded Probe (verifier test)", "owner": "system",
                 "cross_owner": False, "framework": "native", "seeded": True,
                 # Graded by the AI/ML API verifier; native framework → AI/ML API.
                 "gateway": _gateway_for("native"),
                 "worker": SEEDED_PROBE_ID})
    bids.append({"worker": SEEDED_PROBE_ID, "price_usd": 0.0, "relevance": 0.0,
                 "reputation": 0.0, "n_jobs": 0, "framework": "native", "seeded": True,
                 "gateway": _gateway_for("native")})
    hires.append(Hire(worker=SEEDED_PROBE_ID, price_atomic=0, value=0.0, relevance=0.0))
    payout[SEEDED_PROBE_ID] = payout_fallback

    # Ablation gate ON for the demo: hardens the verifier (verbatim-quote +
    # ablation routing + escalate-on-absent) — it only penalizes/escalates,
    # never auto-withholds, so it can't regress false-withhold-0%.
    verifier = Verifier(make_backend("aimlapi", verifier_model),
                        document_label=document_label_for(kind), ablation_gate=True)
    gate = make_x402_gate(
        _env("EVM_PRIVATE_KEY"),
        facilitator_url=os.getenv("X402_FACILITATOR_URL", "https://x402.org/facilitator"),
        network=os.getenv("X402_NETWORK", "eip155:84532"),
        asset_address=os.getenv("X402_USDC_ADDRESS",
                                "0x036CbD53842c5426634e7929541eC2318f3dCF7e"),
    )
    await gate.ensure_permit2_approval()

    # Drift telemetry: every live specialist ran the same configured worker model;
    # the accepted bid per worker is the hire price. The store persists under
    # data/ so a worker's history accumulates across live runs (the baseline a
    # FUTURE run's drift check compares against). The first few live runs will
    # have a NO_BASELINE drift report (nothing to compare against yet) — honest.
    from agent_exchange.anomaly.telemetry import JsonTelemetryStore

    drift_store = JsonTelemetryStore(os.path.join(_ROOT, "data", "telemetry", "telemetry.json"))
    drift_models = {h.worker: model for h in hires}
    drift_bids_atomic = {h.worker: h.price_atomic for h in hires}

    return RunContext(
        mode="live", kind=kind, document_label=document_label_for(kind),
        market_band=market, work_room_id=work_room_id, pool=pool, team=team,
        reporter=reporter, verifier=verifier, hires=hires, payout_addresses=payout,
        gate=gate, signer_key=_env("EVM_PRIVATE_KEY"), bids=bids,
        drift_store=drift_store, drift_models=drift_models,
        drift_bids_atomic=drift_bids_atomic, drift_now_ms=_now_ms(),
        closeables=closeables, recruit_messages=recruit_messages,
    )


# ---------------------------------------------------------------------------
# The lifecycle emitter — drives the real functions, yields (event, data) pairs
# ---------------------------------------------------------------------------

_VERDICT_LABEL = {
    Verdict.CONFIRMED: "confirmed",
    Verdict.PARTIAL: "partial",
    Verdict.UNSUPPORTED: "unsupported",
}


def _usd(atomic: int) -> float:
    """Atomic USDC (6dp) -> human dollars for display."""
    return round(atomic / 1_000_000, 6)


def _now_ms() -> int:
    """Wall-clock now in epoch milliseconds (the telemetry window-ordering key)."""
    return int(datetime.now(timezone.utc).timestamp() * 1000)


def _drift_summary(report: Any) -> str:
    """A short human string describing one worker's drift report (for the UI).

    Prefers the model-substitution tell (the demo's headline catch); falls back
    to a cost/latency note, else the in-baseline / no-baseline state.
    """
    if report.suppressed_reason:
        return f"no baseline yet — {report.suppressed_reason}"
    ms = report.model_substitution
    if ms is not None and ms.flagged:
        if ms.model_switch and ms.price_mismatch and ms.implied_overcharge_ratio:
            prior = ms.baseline_models[0] if ms.baseline_models else "?"
            return (f"model swap: {prior} -> {ms.current_model} "
                    f"at {round(ms.implied_overcharge_ratio, 1)}x markup")
        if ms.model_switch:
            prior = ms.baseline_models[0] if ms.baseline_models else "?"
            return f"model swap: {prior} -> {ms.current_model}"
        if ms.price_mismatch and ms.implied_overcharge_ratio:
            return f"price/model mismatch at {round(ms.implied_overcharge_ratio, 1)}x markup"
    if report.cost is not None:
        return f"cost up {round(report.cost.delta_pct * 100, 1)}% vs baseline"
    if report.latency is not None:
        return f"latency up {round(report.latency.delta_pct * 100, 1)}% vs baseline"
    return "behaving in-baseline"


async def run_job(
    kind: str, document: str, budget_usd: float, requested_mode: str
) -> AsyncIterator[tuple[str, dict]]:
    """Run one marketplace job and yield its lifecycle as ``(event_name, data)`` pairs.

    The SSE event contract the frontend depends on (each ``data`` is the JSON payload):

      * ``stage``        {name, status}  name in discover|bid|hire|collaborate|verify|
                                          settle|done, status in start|end
      * ``document``     {kind, title, document_text, budget_usd} — sent first
      * ``pool``         {agents:[{id,handle,name,owner,cross_owner,framework}]} —
                          ``framework`` in native|langgraph|crewai (which agent
                          framework runs that slot; the LIVE path RUNS it, the sim
                          path LABELS it)
      * ``bid``          {worker, price_usd, relevance, reputation, n_jobs, framework}
                          — one per bid; ``framework`` as above
      * ``hire``         {hired:[{worker,price_usd}], declined:[worker], strategy,
                          pay_fraction_target}
      * ``room_message`` {sender, content} — the collaboration transcript
      * ``progress``     {worker, done:true} — LIVE only; emitted once per posting team
                          member the moment its in-room audit (its ``findings()``)
                          completes during the collaborate phase, so the UI shows each
                          agent finishing progressively (real per-agent progress)
                          instead of all sitting uniformly until verdicts burst at the
                          end. ``worker`` is the specialty key (the same key the
                          pool/bid carry). The sim path does NOT emit ``progress`` (its
                          collaborate is instant/canned).
      * ``finding``      {worker, clause_ref, claim, verdict, confidence, evidence_quote}
      * ``drift``        {worker, flagged, severity, model, baseline_label,
                          model_switch, price_mismatch, overcharge_ratio,
                          cost_delta_pct, latency_delta_pct, summary} — one per
                          worker (flagged OR clean), emitted within the verify
                          flow. The second cheat-signal: a worker that quietly
                          swapped its declared model for a cheaper one while
                          charging the higher price. ``severity`` in info|warn|
                          critical; ``model`` is the model the worker actually
                          ran; ``overcharge_ratio`` / ``cost_delta_pct`` /
                          ``latency_delta_pct`` are null when not computed;
                          floats rounded to 3 dp.
      * ``settle``       {worker, pay_to, authorized_usd, settled_usd, tx_hash, status}
      * ``receipt``      {signer, signature, deliverable_hash}
      * ``done``         {gate_passed, pay_fraction, total_settled_usd,
                          total_withheld_usd, catch_summary}
      * ``error``        {message} — on any failure (graceful; the stream then ends)
    """
    mode = _resolve_mode(requested_mode)
    # Live runs produce events in stage-bursts; pace each item out so the arena
    # animates (staggered bids, verdicts landing one-by-one, room chatter) like
    # the cinematic instead of snapping. Sim-over-/api/run stays instant (0) so
    # tests + the rare sim-via-API path aren't slowed.
    pace = 0.3 if mode == "live" else 0.0
    document = (document or "").strip() or _sample_document(kind)
    budget_usd = budget_usd or _DEFAULT_BUDGET_USD
    ctx: RunContext | None = None
    try:
        # 0. The document the team will audit (sent first so the UI can render it).
        title = _SAMPLE_TITLES.get(kind, kind)
        yield "document", {"kind": kind, "title": title,
                           "document_text": document, "budget_usd": budget_usd}

        # 1. DISCOVER — build the run world (sim or live) and surface the agent pool.
        yield "stage", {"name": "discover", "status": "start"}
        if mode == "live":
            ctx = await _build_live_context(kind, document, budget_usd)
        else:
            ctx = await _build_sim_context(kind, document)
        yield "pool", {"agents": ctx.pool}
        yield "stage", {"name": "discover", "status": "end"}

        # 2. BID — each discovered specialist's asking price (one event per bid).
        yield "stage", {"name": "bid", "status": "start"}
        for b in ctx.bids:
            yield "bid", b
            await asyncio.sleep(pace)
        yield "stage", {"name": "bid", "status": "end"}

        # 3. HIRE — the team selected under budget (here: the bidders that fit).
        yield "stage", {"name": "hire", "status": "start"}
        hired_workers = {h.worker for h in ctx.hires}
        declined = [b["worker"] for b in ctx.bids if b["worker"] not in hired_workers]
        yield "hire", {
            "hired": [{"worker": h.worker, "price_usd": _usd(h.price_atomic)} for h in ctx.hires],
            "declined": declined,
            "strategy": "coverage_within_budget",
            "pay_fraction_target": 1.0,
        }
        # CROSS-OWNER recruit beat — "an agent you don't own joined the room". The live
        # path records these after the real contact-consent handshake; surface them as
        # room_messages right at the hire/recruit moment so the UI shows the cross-org
        # join. Empty on the sim path (the sim marks cross_owner in its pool directly).
        for rm in ctx.recruit_messages:
            yield "room_message", rm
            await asyncio.sleep(pace * 2)  # let the cross-owner join land
        yield "stage", {"name": "hire", "status": "end"}

        # 4. COLLABORATE — the in-room team audit (the real `collaborate_in_room`).
        yield "stage", {"name": "collaborate", "status": "start"}
        # ANTI-STALL: the real `collaborate_in_room` is ~60-90s of LLM work that emits
        # nothing, so the arena reads as frozen. Emit a paced "starting work" beat per
        # posting team member (skip the seeded probe / non-posting members) BEFORE the
        # await, so the agents animate as working. Honest — a real start-of-work beat,
        # not fabricated findings. Sender = the specialty key (the arena resolves room
        # senders by handle AND key, the same key the pool/bid carry as `worker`).
        if mode == "live":
            for m in ctx.team:
                if not m.post_to_room:
                    continue
                yield "room_message", {
                    "sender": m.specialty,
                    "content": f"Reviewing the contract for {m.area}…",
                }
                await asyncio.sleep(pace)
        if mode == "live":
            # LIVE: stream per-agent completion AS EACH specialist's in-room audit
            # finishes. `collaborate_in_room` fires `on_member_complete(specialty)` the
            # moment a member's `findings()` resolves; we funnel those through a queue
            # and drain it WHILE the collaborate task runs, emitting a `progress` event
            # per member. The `task.done()` loop + final drain guarantee termination
            # (never deadlock); `await task` at the end re-raises any failure into the
            # existing error handling, so a collaborate/progress fault still ends the
            # stream cleanly.
            queue: asyncio.Queue[str] = asyncio.Queue()

            async def _on_done(specialty: str) -> None:
                await queue.put(specialty)

            task = asyncio.create_task(
                collaborate_in_room(
                    ctx.work_room_id,
                    document,
                    ctx.team,
                    ctx.reporter,
                    ctx.verifier,
                    on_member_complete=_on_done,
                )
            )
            while not task.done():
                try:
                    worker = await asyncio.wait_for(queue.get(), timeout=0.25)
                    yield "progress", {"worker": worker, "done": True}
                except asyncio.TimeoutError:
                    pass
            while not queue.empty():
                yield "progress", {"worker": queue.get_nowait(), "done": True}
            result = await task  # propagate result + any exception
        else:
            # SIM: collaborate is instant/canned — no progress to stream.
            result = await collaborate_in_room(
                ctx.work_room_id, document, ctx.team, ctx.reporter, ctx.verifier
            )
        # The room transcript: who posted what (best-effort; market may not see it live).
        for msg in await _safe_transcript(ctx.market_band, ctx.work_room_id):
            sender = msg.get("sender_name") or msg.get("sender_id") or "?"
            yield "room_message", {"sender": sender, "content": msg.get("content") or ""}
            await asyncio.sleep(pace * 1.5)  # readable "agents talking" cadence
        yield "stage", {"name": "collaborate", "status": "end"}

        # 5. VERIFY — surface each graded finding (specialists + reporter claims).
        yield "stage", {"name": "verify", "status": "start"}
        for af in result.all_audited:
            v = af.verdict
            yield "finding", {
                "worker": af.finding.worker,
                "clause_ref": af.finding.clause_ref or "",
                "claim": af.finding.claim,
                "verdict": _VERDICT_LABEL[v.verdict],
                "confidence": round(v.confidence, 3),
                "evidence_quote": v.evidence_quote,
                # The seeded probe is honestly labelled so the UI never shows it as a
                # genuine worker — it is the verifier test, caught on purpose.
                "seeded": af.finding.worker == SEEDED_PROBE_ID,
            }
            await asyncio.sleep(pace)  # verdicts land one-by-one (the catch reads)

        # 5b. DRIFT — the SECOND cheat-signal, independent of the verifier: did
        # any worker quietly swap its declared model for a cheaper one while
        # charging the higher price? Emitted within the verify flow (NO new
        # top-level stage). Wrapped so a drift failure degrades gracefully and
        # never breaks the lifecycle stream.
        try:
            async for drift_event in _emit_drift(ctx, document):
                yield drift_event
        except Exception:  # noqa: BLE001 — drift is additive; never break the stream.
            pass
        yield "stage", {"name": "verify", "status": "end"}

        # 6. SETTLE — the x402 verify->settle gate, per worker (the real `settle_job`).
        yield "stage", {"name": "settle", "status": "start"}
        settlement = await settle_job(
            ctx.gate, result, ctx.hires, ctx.payout_addresses, policy=LENIENT
        )
        for w in settlement.workers:
            yield "settle", {
                "worker": w.worker,
                "pay_to": w.pay_to,
                "authorized_usd": _usd(w.authorized_atomic),
                "settled_usd": _usd(w.settled_atomic),
                "tx_hash": w.tx_hash,
                "status": w.status,
            }
        yield "stage", {"name": "settle", "status": "end"}

        # 7. RECEIPT — the EIP-191 signed proof binding the verified work to payment.
        signer = make_receipt_signer(ctx.signer_key)
        receipt = build_receipt(
            ctx.work_room_id, result, settlement,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
        signed = signer.sign(receipt)
        yield "receipt", {
            "signer": signed.signer_address,
            "signature": signed.signature,
            "deliverable_hash": deliverable_hash(result),
        }

        # 8. DONE — the headline outcome.
        n_unsupported = sum(
            af.verdict.verdict is Verdict.UNSUPPORTED for af in result.all_audited
        )
        n_total = len(result.all_audited)
        seeded_caught = any(
            af.finding.worker == SEEDED_PROBE_ID
            and af.verdict.verdict is Verdict.UNSUPPORTED
            for af in result.all_audited
        )
        catch = (f"{n_unsupported} fabricated claim(s) caught and withheld"
                 if n_unsupported else "no fabrication — all claims verified")
        # On the live path one of those catches is the SEEDED verifier test — disclose it.
        seeded_note = (
            " (incl. the seeded verifier-test probe — caught on purpose)"
            if seeded_caught else ""
        )
        yield "stage", {"name": "done", "status": "start"}
        yield "done", {
            "gate_passed": settlement.gate_passed,
            "pay_fraction": round(settlement.pay_fraction, 3),
            "total_settled_usd": _usd(settlement.total_settled_atomic),
            "total_withheld_usd": _usd(settlement.total_withheld_atomic),
            "catch_summary": f"{catch} ({n_total} claims graded){seeded_note}",
            "seeded_probe_caught": seeded_caught,
        }
        yield "stage", {"name": "done", "status": "end"}

    except Exception as exc:  # noqa: BLE001 — any failure ends the stream gracefully.
        yield "error", {"message": f"{type(exc).__name__}: {exc}"}
    finally:
        if ctx is not None:
            for c in ctx.closeables:
                try:
                    await c.aclose()
                except Exception:  # noqa: BLE001 — cleanup must never mask the result.
                    pass


async def _emit_drift(ctx: RunContext, document: str) -> AsyncIterator[tuple[str, dict]]:
    """Evaluate per-worker drift for this run and yield one ``drift`` event each.

    Records each hired worker's current telemetry row, builds its baseline
    (excluding this job), and evaluates drift (see
    :func:`agent_exchange.anomaly.run_drift.evaluate_run_drift`). Emits one
    ``drift`` event per worker — flagged or clean — so the UI can show both. A
    missing store (no drift wiring) yields nothing.
    """
    if ctx.drift_store is None or not ctx.drift_models:
        return

    from agent_exchange.anomaly.run_drift import evaluate_run_drift

    workers = list(ctx.drift_models.keys())
    job_id = ctx.work_room_id or "run"
    reports = evaluate_run_drift(
        ctx.drift_store,
        workers=workers,
        models=ctx.drift_models,
        bid_prices_atomic=ctx.drift_bids_atomic,
        kind=ctx.kind,
        job_id=job_id,
        now_ms=ctx.drift_now_ms,
        contract_text=document,
        latency_ms=_DRIFT_LATENCY_MS,
    )
    for worker in workers:
        report = reports.get(worker)
        if report is None:
            continue
        ms = report.model_substitution
        yield "drift", {
            "worker": worker,
            "flagged": report.flagged,
            "severity": report.overall_severity.value,
            "model": ctx.drift_models[worker],
            "baseline_label": report.baseline_label,
            "model_switch": bool(ms.model_switch) if ms else False,
            "price_mismatch": bool(ms.price_mismatch) if ms else False,
            "overcharge_ratio": (
                round(ms.implied_overcharge_ratio, 3)
                if ms and ms.implied_overcharge_ratio is not None
                else None
            ),
            "cost_delta_pct": (
                round(report.cost.delta_pct, 3) if report.cost is not None else None
            ),
            "latency_delta_pct": (
                round(report.latency.delta_pct, 3) if report.latency is not None else None
            ),
            "summary": _drift_summary(report),
        }


async def _safe_transcript(band: Any, room_id: str) -> list[dict]:
    """Read the room transcript, returning [] on any failure (best-effort).

    The in-memory `FakeBandClient.get_context` only returns messages that @mention the
    CALLING agent — but the demo wants the whole room. For the offline fake we therefore
    read the full message log straight out of the shared world; for the live
    `HttpBandClient` we use ``get_context`` (the real Band ``/context`` returns the shared
    room view).
    """
    try:
        world = getattr(band, "world", None)
        if world is not None and room_id in getattr(world, "rooms", {}):
            return [dict(m) for m in world.rooms[room_id]["messages"]]
        return await band.get_context(room_id)
    except Exception:  # noqa: BLE001
        return []


def _sse(event: str, data: dict) -> str:
    """Format one Server-Sent Event frame (named event + JSON data line)."""
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


# ---------------------------------------------------------------------------
# FastAPI app + endpoints
# ---------------------------------------------------------------------------

app = FastAPI(title="Agent Exchange — live demo API", version="1.0.0")

# CORS — wide-open for the demo so any frontend origin can stream from us.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


class RunRequest(BaseModel):
    """Body for ``POST /api/run``."""

    kind: str = Field(default="contract-audit")
    document: str = Field(default="")
    budget_usd: float = Field(default=_DEFAULT_BUDGET_USD, ge=0.0)
    mode: str = Field(default="sim")  # "live" | "sim"; live degrades to sim if keys absent


@app.get("/health")
async def health() -> dict:
    return {"ok": True}


@app.get("/api/jobs/sample")
async def sample(kind: str = "contract-audit") -> JSONResponse:
    """A sample document + default budget for a job kind, to prefill the UI."""
    doc = _sample_document(kind)
    return JSONResponse({
        "kind": kind,
        "title": _SAMPLE_TITLES.get(kind, kind),
        "document_text": doc,
        "budget_usd": _DEFAULT_BUDGET_USD,
        "document_label": document_label_for(kind),
    })


#: The SSE response headers (shared by the sim + live streams).
_SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",  # disable proxy buffering so events flush live
}


def _project_live_cost(kind: str, document: str, budget_usd: float) -> float:
    """Project the USD provider spend of one LIVE run (for the daily $-cap reservation).

    A live run fans the kind's roster over the document (one model call each on the
    configured worker model) plus one verifier pass — the same shape the audit estimator
    projects. The seeded probe makes no model call (it is canned), so it adds nothing.
    Unknown-price models contribute 0 (honest — never a fabricated number).
    """
    from agent_exchange.workers.job_types import JOB_TYPES

    worker_model = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
    verifier_model = os.getenv("OPENAI_VERIFIER_MODEL", "gpt-4.1")
    job_type = JOB_TYPES.get(kind)
    n_specialists = len(job_type.specialists) if job_type is not None else 6
    doc = (document or "").strip() or _sample_document(kind)
    return _estimate_audit_cost(doc, worker_model, verifier_model, n_specialists)


@app.post("/api/run")
async def run(req: RunRequest):
    """Run a marketplace job and stream its lifecycle as Server-Sent Events.

    SIM mode (the default) is unrestricted (no spend). LIVE mode is gated BEFORE any
    streaming or spend, returning a 429 JSON (never an SSE) when refused:

      * 429 ``live_unavailable``  — live keys are not configured (frontend falls back to
        the recorded run).
      * 429 ``live_busy``         — a live run is already in progress (single-flight).
      * 429 ``live_cap_reached``  — the daily run-count or $ cap is exhausted.

    Once admitted, a live run holds the single-flight flag + its budget reservation until
    the stream ends; both are released in a ``finally`` inside the stream so an error or a
    client disconnect can never wedge the lock or leak the reservation.
    """
    # SIM (or live-degraded-to-sim): no guards, no spend — stream straight through.
    if req.mode != "live":
        async def _sim_stream() -> AsyncIterator[str]:
            async for event, data in run_job(req.kind, req.document, req.budget_usd, "sim"):
                yield _sse(event, data)

        return StreamingResponse(_sim_stream(), media_type="text/event-stream",
                                 headers=_SSE_HEADERS)

    # LIVE — gate before streaming.
    if not _live_keys_present():
        return JSONResponse(
            status_code=429,
            content={
                "error": "live_unavailable",
                "detail": ("live keys are not configured on this server — use the "
                           "recorded run instead (the frontend falls back automatically)"),
            },
        )

    projected = _project_live_cost(req.kind, req.document, req.budget_usd)
    guard = get_live_guard()
    admission = guard.try_acquire(projected_usd=projected)
    if not admission.admitted:
        return JSONResponse(
            status_code=429,
            content={"error": admission.error_code, "detail": admission.detail},
        )

    async def _live_stream() -> AsyncIterator[str]:
        try:
            async for event, data in run_job(req.kind, req.document, req.budget_usd, "live"):
                yield _sse(event, data)
        except Exception as exc:  # noqa: BLE001 — never a 500/half-stream; emit a clean error.
            yield _sse("error", {"message": f"{type(exc).__name__}: {exc}"})
        finally:
            # ALWAYS release the single-flight flag + reconcile the budget reservation,
            # even on error or client disconnect (GeneratorExit also runs this finally).
            guard.release(admission)

    return StreamingResponse(_live_stream(), media_type="text/event-stream",
                             headers=_SSE_HEADERS)


# ---------------------------------------------------------------------------
# POST /api/audit — the verify-only "paste your own contract" endpoint.
#
# This runs the REAL workers + the REAL verifier (ablation gate ON, exactly as the live
# demo) against a document the caller pastes in, and returns the graded findings. It is
# NOT the marketplace lifecycle — there is no Band room, no bidding, no x402 settlement;
# it is purely "fan specialists over the doc, grade their claims, report what was caught".
#
# Because every call is real provider spend, a process-global daily cap (server/
# demo_budget.py) gates it: the projected cost is reserved BEFORE the run and the run is
# refused with 429 once the day's cap is reached. Any worker/verifier failure degrades to
# a clean JSON error — the endpoint never returns a 500 stack.
# ---------------------------------------------------------------------------


class AuditRequest(BaseModel):
    """Body for ``POST /api/audit`` (the locked frontend contract)."""

    kind: str = Field(default="contract-audit")
    document_text: str = Field(default="")


def _audit_models() -> tuple[str, str]:
    """(worker_model, verifier_model) for the audit endpoint, from env with fallbacks."""
    worker = _env("AIMLAPI_MODEL") or _AUDIT_WORKER_MODEL_DEFAULT
    verifier = _env("AIMLAPI_VERIFIER_MODEL") or _AUDIT_VERIFIER_MODEL_DEFAULT
    return worker, verifier


def _audit_catch_summary(n_unsupported: int, n_total: int) -> str:
    """The short human string for the audit result (mirrors the /api/run done event)."""
    if n_total == 0:
        return "no findings to grade"
    if n_unsupported:
        return f"{n_unsupported} fabricated claim(s) caught — payment would be withheld ($0)"
    return f"no fabrication — all {n_total} claim(s) verified"


async def _run_audit(
    kind: str,
    document_text: str,
    *,
    worker_backend: Any = None,
    verifier_backend: Any = None,
) -> dict:
    """Run the verify-only audit and return the locked response dict.

    Fans the kind's specialist roster over ``document_text`` (an `AuditPool`), grades
    every emitted claim with a real `Verifier` (``ablation_gate=True``), and pairs each
    finding with its verdict. ``gate_passed`` is False iff any verdict is ``unsupported``.

    Backends are injectable so tests can pass `MockBackend`s (no network); in production
    they are left ``None`` and built from env via :func:`make_backend` on provider
    ``"aimlapi"``. Raises on a build/run failure — the caller maps that to a clean JSON
    error (never a 500 stack).
    """
    from agent_exchange.workers.pool import AuditPool

    worker_model, verifier_model = _audit_models()

    if worker_backend is None:
        # roster_for builds its own backend from (provider, model) via make_backend.
        specialists = roster_for(kind, "aimlapi", worker_model)
    else:
        # Test/inject path: build the roster on the supplied backend directly.
        from agent_exchange.workers.job_types import JOB_TYPES
        from agent_exchange.workers.specialist import SpecialistWorker

        specialists = [
            SpecialistWorker(name=n, area=a, system_prompt=p, backend=worker_backend)
            for n, a, p in JOB_TYPES[kind].specialists
        ]

    if verifier_backend is None:
        verifier_backend = make_backend("aimlapi", verifier_model)

    pool = AuditPool(specialists)
    findings = await pool.run(document_text)

    verifier = Verifier(
        verifier_backend,
        document_label=document_label_for(kind),
        ablation_gate=True,
    )
    verdicts = await verifier.verify(document_text, [f.claim for f in findings])

    # Pair each finding with its verdict (verify() returns one verdict per claim, in
    # order). A short verdict list (shouldn't happen — verify is per-claim fail-safe)
    # leaves the tail unpaired, which we simply drop rather than guess.
    out_findings: list[dict] = []
    n_confirmed = n_partial = n_unsupported = 0
    for finding, v in zip(findings, verdicts):
        label = _VERDICT_LABEL[v.verdict]
        if v.verdict is Verdict.CONFIRMED:
            n_confirmed += 1
        elif v.verdict is Verdict.PARTIAL:
            n_partial += 1
        else:
            n_unsupported += 1
        out_findings.append({
            "worker": finding.worker,
            "clause_ref": finding.clause_ref or "",
            "claim": finding.claim,
            "verdict": label,
            "confidence": round(v.confidence, 3),
            "evidence_quote": v.evidence_quote,
        })

    n_total = len(out_findings)
    est_cost = _estimate_audit_cost(document_text, worker_model, verifier_model, len(specialists))
    return {
        "kind": kind,
        "n_findings": n_total,
        "n_confirmed": n_confirmed,
        "n_partial": n_partial,
        "n_unsupported": n_unsupported,
        "gate_passed": n_unsupported == 0,
        "catch_summary": _audit_catch_summary(n_unsupported, n_total),
        "est_cost_usd": round(est_cost, 6),
        "findings": out_findings,
    }


def _estimate_audit_cost(
    document_text: str, worker_model: str, verifier_model: str, n_specialists: int
) -> float:
    """Project the USD cost of one audit run (workers fan-out + one verifier pass).

    Each specialist sends ~the document as its prompt; the verifier sends the document
    plus the collected claims once. Unknown-price models contribute 0 (honest — never a
    fabricated number). This same estimate feeds the budget-cap reservation.
    """
    from agent_exchange.core.pricing import estimate_cost

    worker_each = estimate_cost(worker_model, document_text) or 0.0
    verifier_cost = estimate_cost(verifier_model, document_text) or 0.0
    return worker_each * max(1, n_specialists) + verifier_cost


@app.post("/api/audit")
async def audit(req: AuditRequest) -> JSONResponse:
    """Grade a pasted document with the REAL verifier (verify-only, daily-capped).

    Returns the locked response shape on 200. Error responses:
      * 422 — unknown ``kind``.
      * 413 — document larger than ``_AUDIT_MAX_DOC_CHARS``.
      * 429 — the process daily spend cap was reached (``demo_budget_reached``).
      * 500-shaped-as-JSON — any worker/verifier failure (graceful; never a stack).
    """
    kind = (req.kind or "").strip()
    document_text = req.document_text or ""

    # 1. Validate kind (must be a registered job kind).
    if kind not in job_kinds():
        return JSONResponse(
            status_code=422,
            content={
                "error": "unknown_kind",
                "detail": f"kind must be one of {job_kinds()}; got {kind!r}",
            },
        )

    # 2. Size guard.
    if len(document_text) > _AUDIT_MAX_DOC_CHARS:
        return JSONResponse(
            status_code=413,
            content={
                "error": "document_too_large",
                "detail": (
                    f"document_text is {len(document_text)} chars; "
                    f"the limit is {_AUDIT_MAX_DOC_CHARS}"
                ),
            },
        )

    # 3. Budget cap — project cost, reserve against the daily window, refuse if over.
    worker_model, verifier_model = _audit_models()
    # n_specialists for the estimate: the kind's full roster size.
    from agent_exchange.workers.job_types import JOB_TYPES

    n_specialists = len(JOB_TYPES[kind].specialists)
    projected = _estimate_audit_cost(document_text, worker_model, verifier_model, n_specialists)

    guard = get_demo_guard()
    task_id = f"audit-{uuid.uuid4().hex}"
    decision = guard.check_and_reserve(
        task_id, projected_usd=projected, task_label=DEMO_TASK_LABEL
    )
    if not decision.allowed:
        return JSONResponse(
            status_code=429,
            content={
                "error": "demo_budget_reached",
                "detail": (
                    f"the demo's daily spend cap of ${DEMO_DAILY_CAP_USD} has been "
                    "reached — try again tomorrow (the cap resets daily)"
                ),
            },
        )

    # 4. Run — any failure degrades to a clean JSON error; always reconcile the reserve.
    actual = projected
    try:
        result = await _run_audit(kind, document_text)
        actual = float(result["est_cost_usd"])
        return JSONResponse(status_code=200, content=result)
    except Exception as exc:  # noqa: BLE001 — never 500-crash; return a clean JSON error.
        return JSONResponse(
            status_code=500,
            content={"error": "audit_failed", "detail": f"{type(exc).__name__}: {exc}"},
        )
    finally:
        guard.reconcile(task_id, actual_usd=actual)
