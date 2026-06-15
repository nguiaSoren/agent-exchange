"""Job-type registry — routes a job to the right specialist roster + document label.

The marketplace supports more than one kind of audit work. Each `JobType` binds a
job *kind* (the routing key carried on `Job.kind`) to two things: the human-readable
*document label* used in prompts and reports ("contract" vs "NDA"), and the *roster*
of `(name, area, system_prompt)` specialist triples that should be hired for it.

Today two kinds are registered:
  - ``"contract-audit"`` — the general commercial-contract clause-audit pool
    (`specialist.SPECIALISTS`), labelled "contract".
  - ``"nda-review"`` — the NDA-focused review pool (`nda_specialists.NDA_SPECIALISTS`),
    labelled "NDA".

Public API:
  - `JobType`            — a frozen (kind, document_label, specialists) record.
  - `JOB_TYPES`          — the registry: kind -> JobType.
  - `roster_for(kind, provider, model)` — build the `SpecialistWorker`s for a kind.
  - `document_label_for(kind)`          — the document label (default-safe: "contract").
  - `job_kinds()`                       — the registered kinds.
  - `FRAMEWORK_BY_SPECIALTY`            — kind -> {specialty -> framework} routing map.
  - `framework_for(kind, specialty)`    — the framework for a slot (default: "native").

Design notes:
  - The model id is NEVER hardcoded — it flows in from the caller, exactly as in
    `make_pool_specialists`. `roster_for` is the multi-kind generalisation of that
    factory: it constructs one shared backend and fans it out over the kind's roster.
  - `document_label_for` is deliberately default-safe (unknown kind -> "contract") so a
    stale or missing label never breaks the audit pipeline; `roster_for`, by contrast,
    raises on an unknown kind because hiring the wrong roster must fail loudly.
"""

from __future__ import annotations

from dataclasses import dataclass

from .nda_specialists import NDA_SPECIALISTS
from .specialist import SPECIALISTS, SpecialistWorker, make_backend

# ---------------------------------------------------------------------------
# Job type record
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class JobType:
    """One registered kind of audit work.

    Attributes:
        kind: The routing key carried on `Job.kind` (e.g. ``"contract-audit"``).
        document_label: Human-readable noun for the document under audit (e.g.
            ``"contract"`` or ``"NDA"``), used in prompts and reports.
        specialists: The roster of ``(name, area, system_prompt)`` triples to hire for
            this kind — the same shape as `specialist.SPECIALISTS`.
    """

    kind: str
    document_label: str
    specialists: list[tuple[str, str, str]]


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

#: The job-type registry: routing key -> JobType. Add a new kind here to make the
#: marketplace route to a new roster + document label.
JOB_TYPES: dict[str, JobType] = {
    "contract-audit": JobType("contract-audit", "contract", SPECIALISTS),
    "nda-review": JobType("nda-review", "NDA", NDA_SPECIALISTS),
}


# ---------------------------------------------------------------------------
# Cross-framework routing
# ---------------------------------------------------------------------------

#: Which agent FRAMEWORK runs each specialty slot. The marketplace puts a real
#: LangGraph agent (-> AI/ML API) and a real CrewAI agent (-> Featherless) in the
#: room next to native `SpecialistWorker`s — all satisfying the same `Specialist`
#: protocol. Values: ``"native"`` | ``"langgraph"`` | ``"crewai"``. Any specialty
#: not listed (incl. the cross-owner `tax`/`carve_outs` slots) is ``"native"``.
#:
#: This is the SINGLE source of truth for the assignment, imported by both the LIVE
#: path (`server/app.py`, which builds the matching framework worker) and the SIM
#: path (`server/sim.py`, which only LABELS the slot). Keep them in lock-step.
FRAMEWORK_BY_SPECIALTY: dict[str, dict[str, str]] = {
    # TWO CrewAI (-> Featherless) slots per kind so the open-weight side of the
    # market showcases TWO distinct Featherless models (sponsor: Featherless), not
    # one. The pair runs DIFFERENT Featherless models (see FEATHERLESS_TIER below).
    "contract-audit": {"ip": "langgraph", "liability": "crewai", "termination": "crewai"},
    "nda-review": {
        "confidentiality_scope": "langgraph",
        "permitted_use": "crewai",
        "term_survival": "crewai",
    },
}

#: Which Featherless model TIER each CrewAI slot runs, so the two open-weight
#: workers showcase DISTINCT Featherless models. The "primary"/"secondary"
#: indirection keeps the concrete ids env-driven (the server resolves them to
#: ``FEATHERLESS_MODEL`` / ``FEATHERLESS_MODEL_2``) — never hardcoded here (L8).
FEATHERLESS_TIER: dict[str, dict[str, str]] = {
    "contract-audit": {"liability": "primary", "termination": "secondary"},
    "nda-review": {"permitted_use": "primary", "term_survival": "secondary"},
}


def featherless_tier(kind: str, specialty: str) -> str:
    """The Featherless model tier (``"primary"`` | ``"secondary"``) for a CrewAI slot.

    Default-safe: any unmapped (kind, specialty) returns ``"primary"`` so a lone or
    unrecognised Featherless slot still resolves to the configured primary model.
    """
    return FEATHERLESS_TIER.get(kind, {}).get(specialty, "primary")


def framework_for(kind: str, specialty: str) -> str:
    """The agent framework that runs a given specialty slot for a job kind.

    Default-safe: any unmapped (kind, specialty) — including unknown kinds and the
    cross-owner specialties — returns ``"native"``.

    Args:
        kind: A job kind (registered or not).
        specialty: The specialist's specialty key (e.g. ``"ip"``, ``"liability"``).

    Returns:
        ``"native"`` | ``"langgraph"`` | ``"crewai"``.
    """
    return FRAMEWORK_BY_SPECIALTY.get(kind, {}).get(specialty, "native")


# ---------------------------------------------------------------------------
# Registry API
# ---------------------------------------------------------------------------


def roster_for(kind: str, provider: str, model: str) -> list[SpecialistWorker]:
    """Build the specialist roster for a job kind on one shared backend.

    The multi-kind generalisation of `make_pool_specialists`: it looks up the kind's
    roster in `JOB_TYPES`, constructs a single backend (shared by every worker — they
    only read from it), and returns one `SpecialistWorker` per roster entry, in
    registry order.

    The model id is supplied by the caller and applied uniformly to every specialist;
    it is NEVER hardcoded here.

    Args:
        kind: A registered job kind (see `job_kinds`).
        provider: A provider key known to `make_backend`.
        model: The model id to run every specialist on. Required; not hardcoded.

    Returns:
        The `SpecialistWorker`s for that kind's roster, in registry order.

    Raises:
        ValueError: If `kind` is not registered, or if `provider` is unknown
            (the latter propagated from `make_backend`).
        RuntimeError: If the provider's API key env var is unset (from `make_backend`).
    """
    try:
        job_type = JOB_TYPES[kind]
    except KeyError:
        raise ValueError(
            f"unknown job kind {kind!r}; registered kinds: {job_kinds()}"
        ) from None
    backend = make_backend(provider, model)
    return [
        SpecialistWorker(name=name, area=area, system_prompt=system_prompt, backend=backend)
        for name, area, system_prompt in job_type.specialists
    ]


def document_label_for(kind: str) -> str:
    """The human-readable document label for a job kind.

    Default-safe: an unknown or unregistered kind falls back to ``"contract"`` so a
    stale routing key never breaks prompt/report rendering.

    Args:
        kind: A job kind (registered or not).

    Returns:
        The kind's document label, or ``"contract"`` if the kind is unregistered.
    """
    job_type = JOB_TYPES.get(kind)
    return job_type.document_label if job_type is not None else "contract"


def job_kinds() -> list[str]:
    """The registered job kinds, in registry order."""
    return list(JOB_TYPES)
