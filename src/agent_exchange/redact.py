"""Write-time redaction — strip PII from immutable, audit-facing artifacts.

This is a faithful Python port of AgentScope's
``crates/agentscope-storage/src/redact.rs`` (``apply`` + ``Policy``), extended
with a conservative, default-ON PII ``default_policy`` and a ``redact_obj`` walker
so a whole trace row / replay event / receipt dict can be redacted wholesale.

Why write-time (and not read-time): the marketplace's audit artifacts are
*immutable* and *self-verifying* — the JSONL trace, the hash-chained ledger, and
the EIP-191 signed receipts. Redaction is applied **before** any hash or signature
is computed, so the persisted bytes never hold PII *and* the chain / signature still
re-verify over exactly those bytes. Redaction is strictly a PERSISTENCE concern: the
in-flight verifier/graders always see the FULL contract text; only what lands on
disk is redacted.

Match semantics (ported from redact.rs):

  * **Literal keys** — SINGLE pass over the original text, longest-key-first. On a
    match, BOTH the matched key AND its next non-whitespace value token are replaced
    (``OPENAI_API_KEY=sk-…`` → ``[REDACTED:OPENAI_API_KEY]=[REDACTED:OPENAI_API_KEY]``).
    Never re-scans inside a replacement (so ``API_KEY`` can't match inside
    ``[REDACTED:OPENAI_API_KEY]``).
  * **Regex patterns** — replace-all with the template ``[REDACTED:{name}]`` where
    ``{name}`` is the pattern source. Invalid regex is non-fatal (skip + warn).

The default PII policy is deliberately CONSERVATIVE so it never false-matches the
sample MSA / NDA contracts (clause numbers like "twelve (12)", "30 days", section
refs, dates) or the on-chain hex addresses / tx hashes that legitimately live in the
audit trail. Credit-card-like digit runs are only redacted when Luhn-valid (reusing
``verify.graders.luhn_valid``), which rejects clause numbers and zero-padded address
runs.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field, replace
from typing import Callable

from .verify.graders import luhn_valid

# ── replacement template (ported: DEFAULT_REPLACEMENT) ──────────────────────
# ``{name}`` substitutes the matched literal key OR the regex pattern's name.
DEFAULT_REPLACEMENT = "[REDACTED:{name}]"


# ════════════════════════════════════════════════════════════════════════════
# Faithful port of redact.rs::apply  (literal pass + regex pass)
# ════════════════════════════════════════════════════════════════════════════


def _redact_literal_pass(text: str, literal_keys: list[str], replacement_tpl: str) -> str:
    """Single-pass redactor (port of ``redact_literal_pass`` in redact.rs).

    Walks ``text`` cursor-by-cursor; at each position finds the LONGEST matching
    key (case-sensitive prefix match). On match, emits the redacted name, skips the
    ``=``/``:``/whitespace separator, and emits the redacted value. Never re-scans
    inside the replacement (prevents ``API_KEY`` matching inside the replacement of
    ``OPENAI_API_KEY``). Operates on the ORIGINAL text only.
    """
    if not literal_keys:
        return text
    # Longest-first so the longest match wins on shared prefixes
    # (``OPENAI_API_KEY`` beats ``API_KEY``).
    sorted_keys = sorted(literal_keys, key=len, reverse=True)

    out: list[str] = []
    n = len(text)
    cursor = 0
    while cursor < n:
        matched_key: str | None = None
        for key in sorted_keys:
            if key and text.startswith(key, cursor):
                matched_key = key
                break
        if matched_key is None:
            out.append(text[cursor])
            cursor += 1
            continue

        key_replacement = replacement_tpl.replace("{name}", matched_key)
        out.append(key_replacement)
        end = cursor + len(matched_key)

        # Walk past whitespace + an optional single '='/':' separator + whitespace.
        value_start = end
        while value_start < n and text[value_start].isspace():
            value_start += 1
        if value_start < n and text[value_start] in "=:":
            value_start += 1
            while value_start < n and text[value_start].isspace():
                value_start += 1

        # Emit the separator chunk verbatim.
        out.append(text[end:value_start])

        # Value token = up to next whitespace OR end-of-string.
        value_end = value_start
        while value_end < n and not text[value_end].isspace():
            value_end += 1
        if value_end > value_start:
            out.append(key_replacement)
        cursor = value_end
    return "".join(out)


def apply(
    text: str,
    *,
    literal_keys: list[str] | tuple[str, ...] = (),
    regex_patterns: list[str] | tuple[str, ...] = (),
    replacement: str = DEFAULT_REPLACEMENT,
) -> str:
    """Apply the redaction policy to ``text`` (faithful port of ``redact.rs::apply``).

    Pass 1: literal ``literal_keys`` with name + next-non-whitespace-token blanking,
    longest-first, single-pass.
    Pass 2: each regex in ``regex_patterns`` is replace-all'd with the template using
    the pattern source as ``{name}``. An invalid regex is non-fatal: it is skipped and
    a warning is emitted to stderr (mirrors the Rust behavior).

    ``regex_patterns`` may also contain ``GatedPattern`` instances (a pattern plus a
    predicate gate), used for the Luhn-validated credit-card pattern: only matches that
    pass the gate are redacted.
    """
    out = _redact_literal_pass(text, list(literal_keys), replacement)

    for pattern in regex_patterns:
        if isinstance(pattern, GatedPattern):
            out = pattern.apply(out, replacement)
            continue
        try:
            compiled = re.compile(pattern)
        except re.error:
            sys.stderr.write(
                f"agent_exchange.redact: invalid regex pattern (skipped): {pattern!r}\n"
            )
            continue
        # Substitute via a function so the replacement is treated LITERALLY — the
        # pattern source (the `{name}` slot) may contain backslashes (`\d`, `\w`)
        # that re.sub would otherwise interpret as replacement escapes.
        repl = replacement.replace("{name}", pattern)
        out = compiled.sub(lambda _m, _r=repl: _r, out)
    return out


@dataclass(frozen=True, slots=True)
class GatedPattern:
    """A regex pattern whose matches are only redacted when ``gate(match_text)`` is True.

    Used for the credit-card pattern: candidate digit runs are matched broadly, then
    each candidate is replaced ONLY if it is Luhn-valid (so clause numbers, dates, and
    zero-padded on-chain address runs are left untouched). ``name`` is the ``{name}``
    slot used in the replacement so the redaction is labelled distinctly.
    """

    pattern: str
    gate: Callable[[str], bool]
    name: str

    def apply(self, text: str, replacement: str) -> str:
        try:
            compiled = re.compile(self.pattern)
        except re.error:
            sys.stderr.write(
                f"agent_exchange.redact: invalid regex pattern (skipped): {self.pattern!r}\n"
            )
            return text
        repl = replacement.replace("{name}", self.name)

        def _sub(m: re.Match[str]) -> str:
            return repl if self.gate(m.group(0)) else m.group(0)

        return compiled.sub(_sub, text)


# ════════════════════════════════════════════════════════════════════════════
# Conservative default PII policy (default-ON)
# ════════════════════════════════════════════════════════════════════════════
#
# Every pattern below is anchored so it CANNOT false-match the sample MSA / NDA
# contracts (clause numbers, "twelve (12)", "30 days", section refs, dates) nor the
# 0x… hex addresses / tx hashes that legitimately live in the audit trail.

# Email: a@b.tld. Conservative: requires an '@' and a dotted TLD of letters.
_EMAIL = r"(?<![\w.+-])[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}(?![\w.])"

# US phone: optional +1, area code (with or without parens), then 3-4 with a
# REQUIRED separator (space/dot/dash) between groups. Requiring separators avoids
# matching bare digit runs (clause numbers, hex). Bounded by non-word lookarounds.
_PHONE_US = (
    r"(?<![\w.])"
    r"(?:\+?1[-.\s])?"
    r"\(?\d{3}\)?[-.\s]\d{3}[-.\s]\d{4}"
    r"(?![\w])"
)

# E.164 international: a leading '+' (mandatory), country code, then 6-12 digits
# (optionally with single separators). The mandatory '+' prevents matching the
# zero-padded hex address runs (which have no '+').
_PHONE_E164 = r"(?<![\w.])\+\d{1,3}[-.\s]?\d{2,4}(?:[-.\s]?\d{2,4}){1,3}(?![\w])"

# SSN: ddd-dd-dddd, dash-separated (per task spec). The dashes + exact grouping make
# it specific; contract clause refs are not dash-grouped like this.
_SSN = r"(?<![\w-])\d{3}-\d{2}-\d{4}(?![\w-])"

# EIN: dd-ddddddd, dash-separated (per task spec).
_EIN = r"(?<![\w-])\d{2}-\d{7}(?![\w-])"

# Credit-card candidate: 13-19 digits with optional single space/dash separators,
# word-boundary-anchored. Gated through luhn_valid so only real card numbers redact.
_CARD_CANDIDATE = r"(?<![\w])(?:\d[ -]?){12,18}\d(?![\w])"

def _always(_text: str) -> bool:
    return True


# Each default pattern is a GatedPattern so its `{name}` slot is a clean, stable
# audit label (``[REDACTED:EMAIL]`` etc.) rather than the raw regex source. The PII
# patterns gate to always-true; only the credit-card pattern gates on Luhn validity.
_DEFAULT_REGEX_PATTERNS: tuple[object, ...] = (
    GatedPattern(_EMAIL, _always, name="EMAIL"),
    GatedPattern(_PHONE_US, _always, name="PHONE"),
    GatedPattern(_PHONE_E164, _always, name="PHONE"),
    GatedPattern(_SSN, _always, name="SSN"),
    GatedPattern(_EIN, _always, name="EIN"),
    GatedPattern(_CARD_CANDIDATE, luhn_valid, name="CREDIT_CARD"),
)


@dataclass(frozen=True, slots=True)
class Policy:
    """A redaction policy: literal secret keys + regex PII patterns + a template.

    Mirrors ``redact.rs::Policy``. Construct via :func:`default_policy` (conservative
    PII, default-ON) and extend with ``with_literal_keys`` so a job/buyer can pass
    extra secret-key names (e.g. an env-var key) while keeping the default PII set.
    """

    literal_keys: tuple[str, ...] = ()
    regex_patterns: tuple[object, ...] = ()
    replacement: str = DEFAULT_REPLACEMENT

    def apply_to(self, text: str) -> str:
        """Apply this policy to ``text`` (no-op fast path when text isn't a str)."""
        if not isinstance(text, str) or not text:
            return text
        if not self.literal_keys and not self.regex_patterns:
            return text
        return apply(
            text,
            literal_keys=self.literal_keys,
            regex_patterns=self.regex_patterns,
            replacement=self.replacement,
        )

    def with_literal_keys(self, *keys: str) -> Policy:
        """Return a copy with additional literal secret keys merged in (de-duped)."""
        merged = tuple(dict.fromkeys((*self.literal_keys, *keys)))
        return replace(self, literal_keys=merged)


def default_policy(*, extra_literal_keys: tuple[str, ...] | list[str] = ()) -> Policy:
    """The conservative, default-ON PII policy.

    Redacts: email, US/E.164 phone, SSN (``ddd-dd-dddd``), EIN (``dd-ddddddd``), and
    Luhn-valid credit-card digit runs. Optionally seed extra literal secret keys.
    """
    return Policy(
        literal_keys=tuple(extra_literal_keys),
        regex_patterns=_DEFAULT_REGEX_PATTERNS,
        replacement=DEFAULT_REPLACEMENT,
    )


# Module-level default instance, so the write-paths can redact with zero ceremony.
DEFAULT_POLICY = default_policy()


# ════════════════════════════════════════════════════════════════════════════
# redact_obj — walk a dict/list and redact string leaves
# ════════════════════════════════════════════════════════════════════════════


def redact_obj(obj: object, policy: Policy | None = None) -> object:
    """Recursively redact every string leaf of ``obj`` (dict / list / tuple / str).

    Returns a new structure of the same shape with string leaves redacted; non-string
    leaves (ints, floats, bools, None) pass through unchanged. Used to redact a whole
    JobTrace row / replay event / receipt dict before it is hashed/signed/written.

    The policy defaults to :data:`DEFAULT_POLICY` (conservative PII, default-ON). Both
    dict KEYS (left verbatim — field names are schema, not data) and VALUES are walked;
    only values that are strings (or nested containers) are redacted.
    """
    pol = policy if policy is not None else DEFAULT_POLICY
    if isinstance(obj, str):
        return pol.apply_to(obj)
    if isinstance(obj, dict):
        return {k: redact_obj(v, pol) for k, v in obj.items()}
    if isinstance(obj, list):
        return [redact_obj(v, pol) for v in obj]
    if isinstance(obj, tuple):
        return tuple(redact_obj(v, pol) for v in obj)
    return obj
