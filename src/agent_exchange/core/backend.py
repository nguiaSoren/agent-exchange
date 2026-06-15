"""Model backends — THE provider boundary.

ONE adapter (`OpenAICompatBackend`) covers AI/ML API, Featherless, and OpenAI,
because all three speak the OpenAI `POST /chat/completions` API. A "provider" is
therefore just `(base_url, api_key, model, price)`; `make_backend(provider, model)`
wires it from env in one line.

Everything provider-specific — the httpx transport, the OpenAI JSON shape, and the
retry-on-transient/rate/5xx policy — lives HERE and never leaks above. Callers use
the `ModelBackend` interface + canonical types (`Message`/`CompletionResult`) only.
For tests, `MockBackend` implements the same interface with zero network
(the seam is offline-testable by injecting at the boundary, not by bypassing it).
"""

from __future__ import annotations

import os
import re
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass

import httpx
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from .pricing import PRICE_PER_MTOK, price_for  # noqa: F401 — re-exported for callers
from .types import CompletionResult, FinishReason, Message, Usage

# provider → (base_url, api_key_env). All OpenAI-compatible /chat/completions.
PROVIDERS: dict[str, tuple[str, str]] = {
    "aimlapi": ("https://api.aimlapi.com/v1", "AIMLAPI_API_KEY"),
    "featherless": ("https://api.featherless.ai/v1", "FEATHERLESS_API_KEY"),
    "openai": ("https://api.openai.com/v1", "OPENAI_API_KEY"),
}

# PRICE_PER_MTOK is now the filled table from core/pricing.py (20+ models).
# It is imported above and re-exported so existing callers (`from backend import
# PRICE_PER_MTOK`) keep working unchanged. UNKNOWN model → cost is None (honest).

_RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})


def _is_retryable(exc: BaseException) -> bool:
    """L4 — enumerate transient transport errors AND provider rate/5xx statuses.
    One predicate works across all three providers because they share the httpx
    transport (no per-SDK exception hierarchy to special-case)."""
    if isinstance(exc, (httpx.TimeoutException, httpx.ConnectError, httpx.ReadError, httpx.RemoteProtocolError)):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in _RETRY_STATUSES
    return False


def _is_reasoning_family(model: str) -> bool:
    """OpenAI gpt-5 / o-series (and the same models proxied via AI/ML API) require
    `max_completion_tokens` (not `max_tokens`) and only accept the default temperature.
    Match on the model name with any `provider/` prefix stripped."""
    name = model.split("/")[-1]
    return bool(re.match(r"(gpt-5|o1|o3|o4)", name))


def _estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float | None:
    """Resolve model via longest-prefix match then compute cost from live usage counts.

    Uses ``price_for`` (which calls ``resolve_model`` internally) so versioned
    model ids like "claude-3-5-sonnet-20241022" or "gpt-4.1-mini" resolve to
    their table entry even when the exact dated form is absent.  Returns None
    for unknown models — never fabricates a price.
    """
    price = price_for(model)
    if price is None:
        return None  # unknown price → honest None, not a guess
    return (input_tokens * price.input + output_tokens * price.output) / 1_000_000


class ModelBackend(ABC):
    """Async LLM backend. `now_ns` is a swappable clock so tests can pin timing
    deterministically (production MUST leave it on `time.monotonic_ns`)."""

    _clock = staticmethod(time.monotonic_ns)

    @classmethod
    def now_ns(cls) -> int:
        return cls._clock()

    @abstractmethod
    async def complete(
        self,
        messages: list[Message],
        *,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> CompletionResult: ...


@dataclass
class OpenAICompatBackend(ModelBackend):
    """The single real adapter for every OpenAI-compatible provider."""

    provider: str
    model: str
    base_url: str
    api_key: str
    timeout_s: float = 60.0

    async def complete(
        self,
        messages: list[Message],
        *,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> CompletionResult:
        body: dict = {
            "model": self.model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
        }
        if _is_reasoning_family(self.model):
            # gpt-5/o-series: 'max_completion_tokens' (covers reasoning + output tokens),
            # and the only accepted temperature is the default — so we omit `temperature`.
            if max_tokens is not None:
                body["max_completion_tokens"] = max_tokens
        else:
            body["temperature"] = temperature
            if max_tokens is not None:
                body["max_tokens"] = max_tokens
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        url = f"{self.base_url}/chat/completions"

        @retry(
            retry=retry_if_exception(_is_retryable),
            wait=wait_exponential(min=1, max=20),
            stop=stop_after_attempt(4),
            reraise=True,
        )
        async def _call() -> dict:
            async with httpx.AsyncClient(timeout=self.timeout_s) as client:
                r = await client.post(url, json=body, headers=headers)
                r.raise_for_status()
                return r.json()

        submission_ns = self.now_ns()
        data = await _call()
        return_ns = self.now_ns()

        choice = (data.get("choices") or [{}])[0]
        text = ((choice.get("message") or {}).get("content")) or ""
        finish: FinishReason = choice.get("finish_reason") or "unknown"
        if finish not in ("stop", "length", "content_filter", "error"):
            finish = "unknown"

        u = data.get("usage") or {}
        in_tok = int(u.get("prompt_tokens", 0))
        out_tok = int(u.get("completion_tokens", 0))
        usage = Usage(
            input_tokens=in_tok,
            output_tokens=out_tok,
            total_tokens=in_tok + out_tok,  # canonical: ignore a provider's inconsistent total
            estimated_cost_usd=_estimate_cost(self.model, in_tok, out_tok),
        )
        return CompletionResult(
            text=text,
            model=self.model,
            provider=self.provider,
            usage=usage,
            submission_ns=submission_ns,
            return_ns=return_ns,
            finish_reason=finish,
        )


@dataclass
class MockBackend(ModelBackend):
    """Deterministic, networkless backend for offline tests + the seeded-liar harness."""

    provider: str = "mock"
    model: str = "mock-1"
    reply: str = "MOCK audit: 0 risky clauses found."
    finish_reason: FinishReason = "stop"

    async def complete(
        self,
        messages: list[Message],
        *,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> CompletionResult:
        submission_ns = self.now_ns()
        in_tok = sum(len(m.content) for m in messages) // 4  # ~4 chars/token heuristic
        out_tok = max(1, len(self.reply) // 4)
        return_ns = self.now_ns()
        usage = Usage(in_tok, out_tok, in_tok + out_tok, estimated_cost_usd=0.0)
        return CompletionResult(
            text=self.reply,
            model=self.model,
            provider=self.provider,
            usage=usage,
            submission_ns=submission_ns,
            return_ns=return_ns,
            finish_reason=self.finish_reason,
        )


def make_backend(provider: str, model: str, *, timeout_s: float = 60.0) -> OpenAICompatBackend:
    """Wire a real backend from env (the one-config-line factory).

    `make_backend("aimlapi", "gpt-4o-mini")` or `make_backend("featherless", "<model>")`.
    Raises clearly on an unknown provider or a missing API key.
    """
    if provider not in PROVIDERS:
        raise ValueError(f"unknown provider {provider!r}; known: {sorted(PROVIDERS)}")
    base_url, key_env = PROVIDERS[provider]
    api_key = os.environ.get(key_env, "").strip()
    if not api_key:
        raise RuntimeError(f"{key_env} is not set — required for provider {provider!r}")
    return OpenAICompatBackend(
        provider=provider, model=model, base_url=base_url, api_key=api_key, timeout_s=timeout_s
    )
