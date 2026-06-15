"""Worker = a specialist (system prompt) bound to a model backend.

A worker is provider-agnostic: the SAME `Worker` runs whether its `backend` is an
AI/ML API frontier model, a Featherless open-weight model, or a `MockBackend` in a
test — that's the whole point of box 5. `run()` returns a `CompletionResult` carrying
the deliverable text PLUS the instrumentation (latency, tokens, cost) that the
`/metrics` trace records per job.

These workers carry real audit specialties (liability / IP / termination /
tax / data-privacy clause auditors); box 5 is just the substrate they stand on.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..core import CompletionResult, Message, ModelBackend, make_backend


@dataclass(frozen=True)
class Worker:
    """A named specialist. `specialty` is its system prompt; `backend` is its model."""

    name: str
    specialty: str
    backend: ModelBackend

    async def run(
        self,
        task: str,
        *,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> CompletionResult:
        messages = [Message.system(self.specialty), Message.user(task)]
        return await self.backend.complete(messages, temperature=temperature, max_tokens=max_tokens)


def make_worker(name: str, specialty: str, provider: str, model: str) -> Worker:
    """Build a worker on a live provider in one line, e.g.
    `make_worker("liability-bot", LIABILITY_PROMPT, "aimlapi", "gpt-4o-mini")`."""
    return Worker(name=name, specialty=specialty, backend=make_backend(provider, model))
