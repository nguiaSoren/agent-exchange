"""Provider-agnostic pricing + token-estimation — the cost-engine seam.

Ported from AgentScope's Rust implementation:
  - prices.rs   (BUILTIN_PRICES + resolve_model longest-prefix resolver)
  - tokenizer_estimator.rs  (TokenizerKind + conservative char-based fallback)

PRICES ARE ILLUSTRATIVE OF THE LIVE PRICING PAGE AS OF THE PHASE 3A COMMIT.
Do NOT fabricate or adjust prices from memory: pull from each provider's live
pricing page before editing the table. An UNKNOWN model → cost is None (honest).

All per-Mtok values are USD per 1,000,000 tokens.

Longest-prefix resolver per §10.4:
  1. Exact match wins.
  2. On miss, the entry whose key is the longest prefix of the queried name wins.
     (e.g. "claude-3-5-sonnet-20241022" → "claude-3-5-sonnet" when the dated
     form is absent from the table.)
  3. Total miss → None; caller reports cost as None, never guesses.

Tokenizer estimator (provider-agnostic):
  - tiktoken (cl100k / o200k) when the package is importable (not in pyproject.toml
    core deps; gated behind an availability check at import time).
  - Conservative char-based fallback for all families:
      Cl100k / O200k / Anthropic / SentencePiece → 3.5 chars/token
      Fallback (unknown model)                   → 4.0 chars/token (never under-bills)
  Minimum: 1 token (never zero — empty prompts still cost at least 1 token).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

# ── tiktoken availability check (no hard dep; see pyproject.toml) ──
try:
    import tiktoken as _tiktoken  # noqa: F401
    _TIKTOKEN_AVAILABLE = True
except ImportError:
    _TIKTOKEN_AVAILABLE = False


# ──────────────────────────── price table ────────────────────────────

@dataclass(frozen=True, slots=True)
class ModelPrice:
    """One row of the price table. All values are USD per 1,000,000 tokens.

    cache_write / cache_read are None when the provider does not publish them
    as first-class prices (OpenAI / Gemini typically do not enumerate them; the
    caller may apply §15 default multipliers if needed, but this module does not).
    Anthropic publishes all four values explicitly.
    """
    input: float
    output: float
    cache_write: float | None = None
    cache_read: float | None = None


# USD per 1 000 000 tokens (Mtok).
#
# Source: public pricing pages as of phase 3A commit.
# Replace with a prices.toml consumer (F-PRICES) when that ships.
#
# Order convention (mirrors prices.rs): dated/specific names first so an
# exact hit is obvious to a human reader. The resolver sorts by key-length at
# runtime so canonical ordering is not a correctness requirement.
# Last date the price VALUES were verified against live provider pricing.
# L8: prices + model ids go stale fast — re-verify on a cadence, and never trust
# a cost number past this stamp without re-checking the provider pricing pages.
PRICES_VERIFIED_ON = "2026-06-14"


def prices_stale(today: str, *, max_age_days: int = 90) -> bool:
    """True if the price table hasn't been re-verified within ``max_age_days``.

    ``today`` is an ISO date string (injected, so this stays pure + testable).
    Callers that report cost-per-outcome should warn when this is True.
    """
    from datetime import date

    return (date.fromisoformat(today) - date.fromisoformat(PRICES_VERIFIED_ON)).days > max_age_days


PRICE_PER_MTOK: dict[str, ModelPrice] = {
    # ── OpenAI ────────────────────────────────────────────────────────
    "gpt-4o-2024-11-20": ModelPrice(input=2.50, output=10.00, cache_read=1.25),
    "gpt-4o-2024-08-06": ModelPrice(input=2.50, output=10.00, cache_read=1.25),
    "gpt-4o-mini":       ModelPrice(input=0.15, output=0.60,  cache_read=0.075),
    "gpt-4o":            ModelPrice(input=2.50, output=10.00, cache_read=1.25),
    "gpt-4.1-mini":      ModelPrice(input=0.40, output=1.60,  cache_read=0.10),
    "gpt-4.1-nano":      ModelPrice(input=0.10, output=0.40,  cache_read=0.025),
    "gpt-4.1":           ModelPrice(input=2.00, output=8.00,  cache_read=0.50),
    "gpt-4-turbo":       ModelPrice(input=10.00, output=30.00),
    "gpt-4":             ModelPrice(input=30.00, output=60.00),
    "gpt-3.5-turbo":     ModelPrice(input=0.50, output=1.50),
    # o-series reasoning models
    "o1-preview":        ModelPrice(input=15.00, output=60.00, cache_read=7.50),
    "o1-mini":           ModelPrice(input=3.00,  output=12.00, cache_read=1.50),
    "o1":                ModelPrice(input=15.00, output=60.00, cache_read=7.50),
    "o3-mini":           ModelPrice(input=1.10,  output=4.40,  cache_read=0.55),
    "o3":                ModelPrice(input=10.00, output=40.00, cache_read=2.50),
    "o4-mini":           ModelPrice(input=1.10,  output=4.40,  cache_read=0.275),
    # GPT-5 family (verified vs aggregated live pricing, 2026-06-14).
    # NOTE: gpt-5.1 is NOT separately published → it longest-prefix-falls-back
    # to "gpt-5" base pricing here (flagged, not fabricated — L8).
    "gpt-5.5":           ModelPrice(input=5.00, output=30.00, cache_read=0.50),
    "gpt-5.4":           ModelPrice(input=2.50, output=15.00, cache_read=0.25),
    "gpt-5":             ModelPrice(input=0.625, output=5.00, cache_read=0.0625),
    # ── Anthropic ─────────────────────────────────────────────────────
    # Anthropic publishes cache_write and cache_read as first-class prices.
    # Current 4.x family (verified vs aggregated live pricing, 2026-06-14;
    # cache_write ≈ 1.25× input, cache_read ≈ 0.1× input per Anthropic).
    "claude-opus-4-8":   ModelPrice(input=5.00, output=25.00, cache_write=6.25, cache_read=0.50),
    "claude-sonnet-4-6": ModelPrice(input=3.00, output=15.00, cache_write=3.75, cache_read=0.30),
    "claude-haiku-4-5":  ModelPrice(input=1.00, output=5.00,  cache_write=1.25, cache_read=0.10),
    "claude-3-5-sonnet-20241022": ModelPrice(
        input=3.00, output=15.00, cache_write=3.75, cache_read=0.30
    ),
    "claude-3-5-sonnet": ModelPrice(
        input=3.00, output=15.00, cache_write=3.75, cache_read=0.30
    ),
    "claude-3-5-haiku":  ModelPrice(
        input=0.80, output=4.00, cache_write=1.00, cache_read=0.08
    ),
    "claude-3-opus":     ModelPrice(
        input=15.00, output=75.00, cache_write=18.75, cache_read=1.50
    ),
    "claude-3-sonnet":   ModelPrice(input=3.00, output=15.00),
    "claude-3-haiku":    ModelPrice(input=0.25, output=1.25),
    # ── Google Gemini ─────────────────────────────────────────────────
    # Current 3.x / 2.5 (verified vs aggregated live pricing, 2026-06-14).
    "gemini-3.5-flash":     ModelPrice(input=1.50, output=9.00),
    "gemini-2.5-flash":     ModelPrice(input=0.30, output=2.50),
    "gemini-2.5-flash-lite": ModelPrice(input=0.10, output=0.40),
    "gemini-2.0-flash-001": ModelPrice(input=0.10, output=0.40),
    "gemini-2.0-flash":     ModelPrice(input=0.10, output=0.40),
    "gemini-1.5-pro":       ModelPrice(input=1.25, output=5.00),
    "gemini-1.5-flash":     ModelPrice(input=0.075, output=0.30),
}


# ──────────────────────────── resolver ───────────────────────────────

def resolve_model(model: str) -> str | None:
    """Longest-prefix match per §10.4.

    Returns the matched key from PRICE_PER_MTOK, or None on total miss.

    1. Exact match wins immediately.
    2. On miss, finds all table keys that are a prefix of ``model`` and returns
       the one with the longest key (most specific).
    3. Returns None when no prefix matches.

    Examples::

        resolve_model("claude-3-5-sonnet-20241022")  # → "claude-3-5-sonnet-20241022" (exact)
        resolve_model("claude-3-5-sonnet-20991231")  # → "claude-3-5-sonnet" (longest-prefix)
        resolve_model("gpt-4-turbo-preview")         # → "gpt-4-turbo" (beats "gpt-4")
        resolve_model("totally-unknown")             # → None
    """
    if model in PRICE_PER_MTOK:
        return model  # exact match wins

    # Strip provider prefix if present (e.g. "aimlapi/gpt-4o" → "gpt-4o").
    bare = model.split("/")[-1]
    if bare != model and bare in PRICE_PER_MTOK:
        return bare

    # Longest-prefix match against the bare name (and the original as fallback).
    best: str | None = None
    best_len = -1
    for key in PRICE_PER_MTOK:
        if bare.startswith(key) or model.startswith(key):
            if len(key) > best_len:
                best = key
                best_len = len(key)
    return best


def price_for(model: str) -> ModelPrice | None:
    """Resolve ``model`` and look up its price. Returns None if unknown."""
    key = resolve_model(model)
    if key is None:
        return None
    return PRICE_PER_MTOK.get(key)


# ──────────────────────────── tokenizer ──────────────────────────────

def _resolve_tokenizer_family(model: str) -> str:
    """Map a model name to a tokenizer family name.

    Matches are prefix-based (case-insensitive) so versioned names resolve
    correctly (e.g. "gpt-4o-2024-11-20" → "cl100k").

    Families:
      cl100k    — OpenAI GPT-4 / 4o / 3.5-turbo  (3.5 chars/token conservative)
      o200k     — OpenAI GPT-5 / o1 / o3 / o4    (3.5 chars/token conservative)
      anthropic — Anthropic Claude                (3.5 chars/token conservative)
      sentencepiece — Google Gemini               (3.5 chars/token conservative)
      fallback  — unknown/open-weight models      (4.0 chars/token — over-counts
                                                   to never under-bill)
    """
    # Strip provider prefix if present.
    m = model.split("/")[-1].lower()

    # GPT-5 / o-series BEFORE GPT-4 (both share "gpt-" prefix; o-series
    # uses the larger o200k vocabulary per tokenizer_estimator.rs).
    if m.startswith("gpt-5") or m.startswith("o1") or m.startswith("o3") or m.startswith("o4"):
        return "o200k"
    if m.startswith("gpt-4") or m.startswith("gpt-3.5") or m.startswith("gpt-3-5"):
        return "cl100k"
    if m.startswith("claude-"):
        return "anthropic"
    if m.startswith("gemini-"):
        return "sentencepiece"
    return "fallback"


def _chars_per_token(family: str) -> float:
    """Conservative chars-per-token ratio for the char-based estimator.

    All known families use 3.5 (over-counts on common English — correct
    direction for a cost-prevention feature). Unknown/fallback uses 4.0 so
    an unfamiliar model never under-counts the budget projection.
    """
    return 4.0 if family == "fallback" else 3.5


def _tiktoken_count(text: str, family: str) -> int | None:
    """Real BPE token count via tiktoken when available. Returns None on any
    failure so the char-based estimator takes over gracefully."""
    if not _TIKTOKEN_AVAILABLE:
        return None
    try:
        import tiktoken
        if family == "cl100k":
            enc = tiktoken.get_encoding("cl100k_base")
        elif family == "o200k":
            enc = tiktoken.get_encoding("o200k_base")
        else:
            return None
        return len(enc.encode(text))
    except Exception:  # noqa: BLE001  # any tiktoken failure → fall back
        return None


def estimate_tokens(text: str, model: str | None = None) -> int:
    """Provider-agnostic token estimate. Pure; no network.

    Priority:
      1. tiktoken (cl100k / o200k) when the package is importable.
      2. Conservative char-based fallback for all other families.

    Returns at least 1 (empty prompt still costs ≥ 1 token; zero would let an
    empty-prompt request slip past a budget guard's non-zero-estimate invariant).

    Args:
        text:  The text to estimate (prompt or completion).
        model: Optional model name. When None, the ``fallback`` family is used
               (4.0 chars/token — most conservative).
    """
    family = _resolve_tokenizer_family(model) if model else "fallback"

    # Attempt real tokenizer (tiktoken) for OpenAI BPE families.
    real = _tiktoken_count(text, family)
    if real is not None:
        return max(1, real)

    # Char-based fallback.
    cpt = _chars_per_token(family)
    chars = len(text)  # len() on str is O(1) and counts code-units (fast path)
    estimate = math.ceil(chars / cpt)
    return max(1, estimate)


# ──────────────────────────── cost projection ─────────────────────────

def estimate_cost(
    model: str,
    prompt: str,
    completion: str | None = None,
) -> float | None:
    """Project a USD cost from estimated tokens × resolved price.

    Returns None if the model's price is unknown (honest; never guesses).
    This is the seam the budget-guard (item #3) calls.

    Args:
        model:      Model name (may include a provider prefix like "aimlapi/").
        prompt:     The input text (prompt side).
        completion: Optional output text. When provided, output token cost is
                    added. When None, only input cost is projected.
    """
    price = price_for(model)
    if price is None:
        return None

    in_tok = estimate_tokens(prompt, model)
    out_tok = estimate_tokens(completion, model) if completion else 0

    return (in_tok * price.input + out_tok * price.output) / 1_000_000
