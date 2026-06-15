"""Canonical, provider-agnostic message + result types — the boundary types.

"No provider types above adapters": every module OUTSIDE
`backend.py` speaks ONLY these types — `Message`, `Usage`, `CompletionResult`.
The provider transport (httpx) and the OpenAI JSON wire-shape live inside
`backend.py` and never leak upward. Swapping AI/ML API ⇄ Featherless ⇄ OpenAI is
a config change, never a caller change.

Invariants are enforced in `__post_init__`:
token counts ≥ 0, `total == input + output`, cost is `None` or ≥ 0, and a result's
`return_ns ≥ submission_ns` (timestamps are `monotonic_ns`, so latency is always
non-negative — never wall-clock, which goes backwards under NTP).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Role = Literal["system", "user", "assistant"]
FinishReason = Literal["stop", "length", "content_filter", "error", "unknown"]


@dataclass(frozen=True, slots=True)
class Message:
    """One chat message. Provider-agnostic."""

    role: Role
    content: str

    @classmethod
    def system(cls, content: str) -> "Message":
        return cls("system", content)

    @classmethod
    def user(cls, content: str) -> "Message":
        return cls("user", content)

    @classmethod
    def assistant(cls, content: str) -> "Message":
        return cls("assistant", content)


@dataclass(frozen=True, slots=True)
class Usage:
    """Token + cost accounting for one model call. Cost is `None` when the model's
    price isn't known (we never fabricate a price — see `backend.PRICE_PER_MTOK`)."""

    input_tokens: int
    output_tokens: int
    total_tokens: int
    estimated_cost_usd: float | None = None

    def __post_init__(self) -> None:
        if min(self.input_tokens, self.output_tokens, self.total_tokens) < 0:
            raise ValueError("token counts must be >= 0")
        if self.total_tokens != self.input_tokens + self.output_tokens:
            raise ValueError(
                f"total_tokens {self.total_tokens} != input {self.input_tokens} + "
                f"output {self.output_tokens}"
            )
        if self.estimated_cost_usd is not None and self.estimated_cost_usd < 0:
            raise ValueError(f"estimated_cost_usd must be None or >= 0, got {self.estimated_cost_usd}")


@dataclass(frozen=True, slots=True)
class CompletionResult:
    """One model call's result + full instrumentation (feeds the `/metrics` trace).

    `submission_ns`/`return_ns` are `time.monotonic_ns()` marks taken immediately
    before/after the call — `latency_ms` is therefore always non-negative.
    """

    text: str
    model: str
    provider: str
    usage: Usage
    submission_ns: int
    return_ns: int
    finish_reason: FinishReason = "stop"

    def __post_init__(self) -> None:
        if self.return_ns < self.submission_ns:
            raise ValueError("return_ns must be >= submission_ns (use monotonic_ns, not wall clock)")

    @property
    def latency_ms(self) -> float:
        return (self.return_ns - self.submission_ns) / 1e6

    @property
    def early_termination(self) -> bool:
        """Truncated/cut for any reason (length cap, content filter) — not a clean stop."""
        return self.finish_reason in ("length", "content_filter")

    @property
    def cost_usd(self) -> float | None:
        return self.usage.estimated_cost_usd
