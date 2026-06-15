"""Backend substrate tests — all offline (MockBackend), no network.

Covers: canonical-type invariants, the swappable monotonic clock, the MockBackend +
Worker happy path, the L4 retry predicate, the make_backend factory (env wiring +
clear failures), and that the provider boundary holds (the OpenAI-compatible adapter
is the only thing that knows a base_url).

Run: `python3 tests/test_workers.py`  (or `pytest` once dev extras are installed).
"""

from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import httpx

from agent_exchange.core import (
    PROVIDERS,
    CompletionResult,
    Message,
    MockBackend,
    Usage,
    make_backend,
)
from agent_exchange.core.backend import _estimate_cost, _is_retryable
from agent_exchange.workers import Worker


# ── canonical-type invariants ──

def test_usage_invariants():
    Usage(10, 5, 15)  # ok
    Usage(10, 5, 15, estimated_cost_usd=None)  # ok
    Usage(0, 0, 0, estimated_cost_usd=0.0)  # ok
    for bad in [
        lambda: Usage(10, 5, 99),          # total != in+out
        lambda: Usage(-1, 0, -1),          # negative
        lambda: Usage(1, 1, 2, estimated_cost_usd=-0.1),  # negative cost
    ]:
        try:
            bad()
            raise AssertionError("expected ValueError")
        except ValueError:
            pass


def test_completionresult_timestamp_invariant_and_views():
    r = CompletionResult("hi", "m", "p", Usage(4, 2, 6), submission_ns=1_000_000, return_ns=4_000_000)
    assert r.latency_ms == 3.0
    assert r.early_termination is False
    r2 = CompletionResult("hi", "m", "p", Usage(4, 2, 6), 1, 1, finish_reason="length")
    assert r2.early_termination is True  # truncated
    try:
        CompletionResult("x", "m", "p", Usage(1, 1, 2), submission_ns=10, return_ns=5)
        raise AssertionError("return_ns < submission_ns must raise")
    except ValueError:
        pass


# ── swappable clock + MockBackend + Worker ──

def test_mock_backend_and_worker_offline():
    backend = MockBackend(reply="MOCK audit: 2 risky clauses.")
    worker = Worker("liability-bot", "You audit contracts for liability clauses.", backend)
    result = asyncio.run(worker.run("Audit this MSA for liability caps."))
    assert result.text == "MOCK audit: 2 risky clauses."
    assert result.provider == "mock"
    assert result.usage.input_tokens > 0 and result.usage.output_tokens > 0
    assert result.usage.total_tokens == result.usage.input_tokens + result.usage.output_tokens
    assert result.return_ns >= result.submission_ns
    assert result.cost_usd == 0.0


def test_clock_is_swappable_for_deterministic_timing():
    ticks = iter([1_000_000_000, 1_002_500_000])  # 2.5 ms apart
    MockBackend._clock = staticmethod(lambda: next(ticks))
    try:
        r = asyncio.run(MockBackend().complete([Message.user("x")]))
        assert r.latency_ms == 2.5
    finally:
        import time
        MockBackend._clock = staticmethod(time.monotonic_ns)  # restore (G-DETERMINISM)


# ── L4 retry predicate ──

def test_is_retryable_predicate():
    req = httpx.Request("POST", "https://x/y")
    assert _is_retryable(httpx.ConnectError("boom")) is True
    assert _is_retryable(httpx.ReadTimeout("slow")) is True
    for code in (429, 500, 502, 503, 504):
        exc = httpx.HTTPStatusError("e", request=req, response=httpx.Response(code, request=req))
        assert _is_retryable(exc) is True
    for code in (400, 401, 403, 404, 422):
        exc = httpx.HTTPStatusError("e", request=req, response=httpx.Response(code, request=req))
        assert _is_retryable(exc) is False
    assert _is_retryable(ValueError("unrelated")) is False


# ── factory + provider boundary ──

def test_make_backend_wiring_and_failures():
    try:
        make_backend("nope", "m")
        raise AssertionError("unknown provider must raise ValueError")
    except ValueError:
        pass

    os.environ.pop("FEATHERLESS_API_KEY", None)
    try:
        make_backend("featherless", "m")
        raise AssertionError("missing key must raise RuntimeError")
    except RuntimeError:
        pass

    os.environ["AIMLAPI_API_KEY"] = "test-key"
    b = make_backend("aimlapi", "gpt-4o-mini")
    assert b.base_url == "https://api.aimlapi.com/v1"  # provider → base_url mapping
    assert b.api_key == "test-key"
    assert ("aimlapi", "featherless", "openai") == tuple(sorted(PROVIDERS))


def test_cost_is_none_when_price_unknown():
    # honest: unknown model → no fabricated price (L6)
    assert _estimate_cost("some-unpriced-model", 1000, 1000) is None


def _run_all():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"  ✓ {fn.__name__}")
    print(f"\n{len(fns)} passed")


if __name__ == "__main__":
    _run_all()
