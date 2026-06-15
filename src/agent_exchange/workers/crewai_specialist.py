"""A clause-audit specialist whose *brain* runs through **CrewAI** — a genuinely
different agent framework — bound to **Featherless** (open-weight inference).

This is the cross-framework proof for the Agent Exchange marketplace: the same
`Specialist` seam that `SpecialistWorker` (native, direct HTTP) satisfies is here
satisfied by a real CrewAI `Agent`/`Task`/`Crew`, so the room contains a true
CrewAI + open-weight agent bidding and working alongside native peers.

Why it stays interchangeable with the native worker:
  - SAME contract — it satisfies the `Specialist` protocol (`.name` +
    `async findings(contract) -> list[Finding]`), so a pool fans out over it
    identically.
  - SAME prompt — it is constructed from the EXACT `(name, area, system_prompt)`
    triples exported as `SPECIALISTS` / `NDA_SPECIALISTS`. The system prompt already
    pins the JSON output contract `parse_findings` consumes, so the CrewAI output
    shape matches the native worker's byte-for-byte.
  - SAME parser — the crew's text result is handed straight to the shared,
    fail-soft `parse_findings`. No bespoke parsing; garbage → `[]`, never a raise.

CrewAI specifics (verified against CrewAI 1.14.7 + a live Featherless call,
2026-06-15 — L8):
  - `crewai.LLM` is a Pydantic model. For an OpenAI-compatible CUSTOM endpoint in
    1.14.7 (which dropped the bundled LiteLLM fallback), the working config is a
    BARE model id + ``provider="openai"`` (forces the native OpenAI client) +
    ``base_url`` pointed at Featherless. Note: do NOT prepend the ``openai/``
    LiteLLM prefix here — the native client passes ``model`` through verbatim, so a
    prefixed id 404s; ``provider="openai"`` is what selects the OpenAI transport.
  - `Crew.kickoff()` is SYNC and returns a `CrewOutput` whose `.raw` holds the final
    text. We wrap it in `asyncio.to_thread` so `findings` stays `async` (CrewAI also
    exposes `kickoff_async`, but `to_thread` keeps the offline-injection seam simple
    and uniform).

Offline-testable by construction: pass an injected `llm` (any object CrewAI's
`Agent` accepts — including a fake), OR monkeypatch `Crew.kickoff`. Tests never
touch the network.
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass, field
from typing import Any

from ..core.backend import PROVIDERS
from .finding import Finding, Specialist, parse_findings

# Featherless = open-weight, OpenAI-compatible. The base_url is the single source of
# truth in `backend.PROVIDERS`; we reuse it so the CrewAI binding can never drift from
# the native one.
_FEATHERLESS_BASE_URL, _FEATHERLESS_KEY_ENV = PROVIDERS["featherless"]


def _build_featherless_llm(model: str) -> Any:
    """Construct a CrewAI `LLM` pointed at Featherless (open-weight, OpenAI-compatible).

    Imported lazily so importing this module never requires CrewAI to be installed
    (only constructing a real, non-injected `CrewAISpecialist` does).

    The config — bare ``model`` id + ``provider="openai"`` + custom ``base_url`` —
    is the verified-working shape for CrewAI 1.14.7's native OpenAI client against a
    custom OpenAI-compatible endpoint (see module docstring).

    Args:
        model: The Featherless model id (e.g. ``"Qwen/Qwen2.5-72B-Instruct"``). Never
            defaulted from memory — it flows in from the caller / ``FEATHERLESS_MODEL``.

    Returns:
        A configured `crewai.LLM`.

    Raises:
        RuntimeError: If ``FEATHERLESS_API_KEY`` is unset.
        ImportError: If CrewAI is not installed.
    """
    from crewai import LLM  # lazy: only needed for the live path

    api_key = os.environ.get(_FEATHERLESS_KEY_ENV, "").strip()
    if not api_key:
        raise RuntimeError(
            f"{_FEATHERLESS_KEY_ENV} is not set — required to run CrewAISpecialist on Featherless"
        )
    return LLM(
        model=model,
        provider="openai",  # force CrewAI's native OpenAI client at the custom base_url
        base_url=_FEATHERLESS_BASE_URL,
        api_key=api_key,
        temperature=0.0,  # determinism/auditability; the prompt does all the steering
    )


@dataclass
class CrewAISpecialist:
    """A `Specialist` whose reasoning runs as a CrewAI `Agent`/`Task`/`Crew` on Featherless.

    Mirrors `SpecialistWorker`'s shape (`name` / `area` / `system_prompt`) so the two
    are drop-in interchangeable behind the `Specialist` protocol — the only difference
    is the engine underneath. Construct one straight from a `SPECIALISTS` triple.

    Attributes:
        name: Stable specialist id (e.g. ``"liability"``). Stamped onto every
            `Finding.worker`; MUST be unique within a pool to keep findings attributable
            (and payable) to the right worker.
        area: Short human-readable clause area (feeds the CrewAI agent's *goal*).
        system_prompt: The engineered instruction that scopes the agent to its area AND
            pins the exact JSON output contract `parse_findings` consumes. REUSED
            verbatim from `SPECIALISTS` / `NDA_SPECIALISTS` so output shape matches the
            native worker.
        llm: An injected CrewAI LLM (or any object CrewAI's `Agent` accepts). When
            ``None``, a real Featherless `LLM` is built lazily on first use from
            ``model``. Injecting a fake here is the primary offline-test seam.
        model: The Featherless model id used iff ``llm`` is ``None``; defaults to the
            ``FEATHERLESS_MODEL`` env var (never hardcoded — L8). Only read on the live
            path, so tests that inject ``llm`` never need it set.
    """

    name: str
    area: str
    system_prompt: str
    llm: Any | None = None
    model: str | None = field(default=None)

    def _resolve_llm(self) -> Any:
        """Return the injected LLM, or lazily build a real Featherless one (cached)."""
        if self.llm is None:
            model = self.model or os.environ.get("FEATHERLESS_MODEL", "").strip()
            if not model:
                raise RuntimeError(
                    "no LLM injected and FEATHERLESS_MODEL is unset — cannot pick a model "
                    "from memory (L8); set FEATHERLESS_MODEL or pass llm=/model="
                )
            self.llm = _build_featherless_llm(model)
        return self.llm

    def _run_crew(self, contract: str) -> str:
        """Build + run a real CrewAI crew for this clause area; return the raw text.

        Sync (CrewAI's `kickoff` is sync); `findings` calls this via `asyncio.to_thread`.
        The agent's role/goal/backstory are derived from the area + system prompt, and
        the task description carries the full contract plus the same JSON return
        instruction the native worker appends, so the crew emits the JSON array shape
        `parse_findings` already understands.
        """
        from crewai import Agent, Crew, Task  # lazy: live path only

        agent = Agent(
            role=f"{self.name} clause-audit specialist",
            goal=f"Audit ONLY the {self.area} of the contract and report checkable findings as JSON.",
            backstory=self.system_prompt,
            llm=self._resolve_llm(),
            verbose=False,
            allow_delegation=False,
        )
        task = Task(
            description=(
                f"{self.system_prompt}\n\n"
                "CONTRACT TO AUDIT:\n"
                f"{contract}\n\n"
                "Return your findings now as the JSON array."
            ),
            expected_output=(
                "A single JSON array of findings, each "
                '{"clause_ref": "...", "claim": "...", "severity": "low|medium|high"}. '
                "No prose, no markdown fences."
            ),
            agent=agent,
        )
        crew = Crew(agents=[agent], tasks=[task], verbose=False)
        result = crew.kickoff()
        # CrewOutput → final text via .raw; fall back to str() defensively.
        return getattr(result, "raw", None) or str(result)

    async def findings(self, contract: str) -> list[Finding]:
        """Audit one contract for this specialist's clause area, via CrewAI on Featherless.

        Runs the (sync) crew off the event loop with `asyncio.to_thread`, then parses the
        result with the shared `parse_findings`. Fail-soft end to end: any framework error
        OR non-conforming output yields ``[]`` — a misbehaving CrewAI worker produces no
        spurious payable findings rather than raising into the pool fan-out.

        Args:
            contract: The full contract text to audit.

        Returns:
            The parsed findings, each tagged with ``worker == self.name``. May be empty.
        """
        try:
            text = await asyncio.to_thread(self._run_crew, contract)
        except Exception:
            # Fail-soft: a flaky crew/LLM never crashes the pool — it just earns nothing.
            return []
        return parse_findings(text, self.name)


# Static conformance check: CrewAISpecialist honours the Specialist protocol
# (no runtime cost; mypy-visible). If the protocol drifts, this line stops type-checking.
_: type[Specialist] = CrewAISpecialist
