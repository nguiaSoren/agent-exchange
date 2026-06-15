"""A clause-audit specialist whose *brain* runs through **LangGraph** — a genuinely
different agent framework — instead of the native `OpenAICompatBackend`.

The point of this module is **cross-framework** collaboration: the marketplace can put
a real LangGraph agent in the room next to the native `SpecialistWorker`, and both
satisfy the SAME `Specialist` protocol, emit the SAME `Finding` shape, and are graded
by the same verifier. Interoperability comes for free because this worker REUSES the
two locked seams instead of reinventing them:

  - the SAME engineered system prompts (`specialist.SPECIALISTS` / `nda_specialists`)
    — so the model is steered to emit the EXACT JSON output contract the verifier
    expects; and
  - the SAME fail-soft parser (`finding.parse_findings`) — so garbage output yields
    `[]` (nothing to verify, nothing to pay) rather than raising.

What is genuinely LangGraph here: `findings()` builds a minimal **StateGraph** with a
single model node, `compile()`s it, and drives it with `ainvoke()` — not a bare LLM
call. The model itself is a LangChain `BaseChatModel`; by default a `ChatOpenAI`
pointed at **AI/ML API** (OpenAI-compatible), but ANY chat model can be **injected**
at the constructor boundary, which is how tests run fully offline (a fake chat model)
without bypassing the graph.

Public API:
  - `LangGraphSpecialist` — a `Specialist`-protocol worker backed by a LangGraph graph.
  - `langgraph_roster_for(kind, *, model=None)` — build a kind's roster as LangGraph
    specialists (the cross-framework parallel to `job_types.roster_for`).

Design notes:
  - The model id is NEVER hardcoded — it flows in from the caller or from the
    `AIMLAPI_MODEL` env var (read once, at default-LLM construction time).
  - `temperature=0` for determinism/auditability; the prompts do all the steering.
  - Constructed lazily: the default `ChatOpenAI` (and the `AIMLAPI_API_KEY` lookup) is
    built on first `findings()` call, so a `LangGraphSpecialist` can be *defined* in an
    environment without the key as long as an `llm` is injected.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from typing_extensions import TypedDict

from langgraph.graph import END, START, StateGraph

from .finding import Finding, Specialist, parse_findings

if TYPE_CHECKING:  # avoid importing heavy LangChain types at module import time
    from langchain_core.language_models.chat_models import BaseChatModel

# The instruction appended to the contract, mirroring `SpecialistWorker.findings` so the
# model is asked for its output in the identical way regardless of which framework drives it.
_RETURN_INSTRUCTION = "\n\nReturn your findings now as the JSON array."

# AI/ML API is OpenAI-compatible; mirror `core.backend.PROVIDERS["aimlapi"]`.
_AIMLAPI_BASE_URL = "https://api.aimlapi.com/v1"
_AIMLAPI_KEY_ENV = "AIMLAPI_API_KEY"
_AIMLAPI_MODEL_ENV = "AIMLAPI_MODEL"
_DEFAULT_MODEL = "anthropic/claude-haiku-4.5"


class _AuditState(TypedDict):
    """The LangGraph state channels for one audit pass.

    `contract` is the input the orchestrator hands in; `text` is the raw model
    completion the model node writes back, which `findings()` then parses.
    """

    contract: str
    text: str


@dataclass
class LangGraphSpecialist:
    """A single clause-area audit specialist whose reasoning runs on a LangGraph graph.

    Satisfies the `Specialist` protocol (`.name` + `async findings(contract)`), so the
    pool fans out over it identically to a native `SpecialistWorker` — the framework
    behind a worker is invisible to the pool, the verifier, and the settlement gate.

    Attributes:
        name: Stable identifier stamped onto every `Finding.worker` (e.g.
            ``"liability"``). MUST be unique within a pool for findings to be
            attributable — and therefore payable — to the right worker.
        area: Short human-readable description of the clause area audited.
        system_prompt: The engineered instruction that scopes the model to this area
            and pins the exact JSON output contract. REUSED verbatim from
            `specialist.SPECIALISTS` / `nda_specialists.NDA_SPECIALISTS`, so the
            LangGraph output shape matches what `parse_findings` consumes.
        llm: An optional injected LangChain chat model. When ``None``, a default
            `ChatOpenAI` pointed at AI/ML API is built lazily on first use. Injection
            is the test/offline seam: a fake chat model runs the graph with no network.
        model: Optional model id override for the default `ChatOpenAI`. When ``None``,
            falls back to ``AIMLAPI_MODEL`` env, then to the served default. Ignored
            when ``llm`` is injected.
    """

    name: str
    area: str
    system_prompt: str
    llm: "BaseChatModel | None" = None
    model: str | None = None
    # Compiled graph is cached after first build (the graph is stateless across calls).
    _graph: object | None = field(default=None, init=False, repr=False, compare=False)

    def _ensure_llm(self) -> "BaseChatModel":
        """Return the injected chat model, or lazily build the default AI/ML API one.

        Built lazily so a `LangGraphSpecialist` can be *constructed* without
        ``AIMLAPI_API_KEY`` present (e.g. in tests that inject an `llm`); the key is
        only required when a real default model must actually run.
        """
        if self.llm is not None:
            return self.llm
        from langchain_openai import ChatOpenAI  # local import: keep module import light

        api_key = os.environ.get(_AIMLAPI_KEY_ENV, "").strip()
        if not api_key:
            raise RuntimeError(
                f"{_AIMLAPI_KEY_ENV} is not set — required to build the default "
                "ChatOpenAI for LangGraphSpecialist (inject `llm=` to run offline)"
            )
        model = self.model or os.environ.get(_AIMLAPI_MODEL_ENV, _DEFAULT_MODEL)
        self.llm = ChatOpenAI(
            base_url=_AIMLAPI_BASE_URL,
            api_key=api_key,
            model=model,
            temperature=0,
        )
        return self.llm

    def _build_graph(self) -> object:
        """Compile the minimal LangGraph: START → model node → END.

        The model node sends ``[system, contract + return-instruction]`` to the chat
        model and writes the raw completion text into state. Cached after first build.
        """
        if self._graph is not None:
            return self._graph

        from langchain_core.messages import HumanMessage, SystemMessage

        async def _model_node(state: _AuditState) -> dict[str, str]:
            llm = self._ensure_llm()
            messages = [
                SystemMessage(content=self.system_prompt),
                HumanMessage(content=state["contract"] + _RETURN_INSTRUCTION),
            ]
            response = await llm.ainvoke(messages)
            content = getattr(response, "content", "")
            # LangChain message content can be a str or a list of content blocks;
            # normalise to the plain text `parse_findings` expects (fail-soft → "").
            if isinstance(content, list):
                content = "".join(
                    part.get("text", "") if isinstance(part, dict) else str(part)
                    for part in content
                )
            return {"text": content if isinstance(content, str) else str(content)}

        builder: StateGraph = StateGraph(_AuditState)
        builder.add_node("audit", _model_node)
        builder.add_edge(START, "audit")
        builder.add_edge("audit", END)
        self._graph = builder.compile()
        return self._graph

    async def findings(self, contract: str) -> list[Finding]:
        """Audit one contract for this specialist's clause area, via LangGraph.

        Drives a compiled StateGraph with `ainvoke`, then parses the model's output
        with the shared `parse_findings`. Fail-soft by construction: any non-conforming
        output (or an empty ``[]`` when the area is absent) becomes an empty list, so a
        misbehaving model produces no spurious payable work rather than raising.

        Args:
            contract: The full contract text to audit.

        Returns:
            The parsed findings, each tagged with ``worker == self.name``. May be empty.
        """
        graph = self._build_graph()
        result = await graph.ainvoke({"contract": contract, "text": ""})  # type: ignore[attr-defined]
        return parse_findings(result.get("text", ""), self.name)


# A static check that the worker honours the protocol (no runtime cost; mypy-visible).
_: type[Specialist] = LangGraphSpecialist


# ---------------------------------------------------------------------------
# Roster factory
# ---------------------------------------------------------------------------


def langgraph_roster_for(kind: str, *, model: str | None = None) -> list[LangGraphSpecialist]:
    """Build a job kind's roster as LangGraph specialists on AI/ML API.

    The cross-framework parallel to `job_types.roster_for`: it looks up the kind's
    ``(name, area, system_prompt)`` triples in `JOB_TYPES` and wraps each in a
    `LangGraphSpecialist`. Each gets its own default `ChatOpenAI` (built lazily on
    first use), so no shared mutable backend is needed.

    The model id is NEVER hardcoded — it flows in via ``model`` or, when ``None``,
    from the ``AIMLAPI_MODEL`` env var at first-use time.

    Args:
        kind: A registered job kind (see `job_types.job_kinds`).
        model: Optional model id applied to every specialist's default `ChatOpenAI`.

    Returns:
        One `LangGraphSpecialist` per roster entry, in registry order.

    Raises:
        ValueError: If `kind` is not registered.
    """
    from .job_types import JOB_TYPES

    try:
        job_type = JOB_TYPES[kind]
    except KeyError:
        raise ValueError(
            f"unknown job kind {kind!r}; registered kinds: {list(JOB_TYPES)}"
        ) from None
    return [
        LangGraphSpecialist(name=name, area=area, system_prompt=system_prompt, model=model)
        for name, area, system_prompt in job_type.specialists
    ]
