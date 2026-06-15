"""Deterministic claim-vs-evidence graders — the ungameable, model-free layer.

Ported faithfully from AgentScope's Rust `agentscope-errors` helpers (same math,
idiomatic Python, pure stdlib). These functions are the load-bearing hardening
behind the product promise: *every finding must quote text that actually EXISTS in
the document* — a deterministic check, never an LLM call. They are pure, total
(never raise on ordinary input), and deterministic across invocations.

Functions
---------
- ``substring_overlap_ratio(claim, evidence)`` — fraction of a claim's distinctive
  length-10+ character substrings that appear verbatim in the evidence. The killer
  signal for "did this quote actually come from that document?".
- ``token_jaccard_distinctive(a, b)`` — Jaccard over distinctive tokens (top-100
  English stopwords filtered).
- ``js_divergence(a, b)`` — Jensen-Shannon divergence (base-2) between the two term
  distributions. 0 = identical distributions (low penalty); 1 = fully disjoint
  (high penalty).
- ``extracted_claims(text)`` — regex extraction of atomic facts (date / number /
  currency / entity / url / path) as ``ExtractedAtom``s.
- ``luhn_valid(number)`` — standard Luhn (mod-10) checksum (13–19 digits).
- ``violates_declared_constraints(output, rubric)`` — declared-constraint checking
  (word limit / "as JSON" / character limit), returns a list of human-readable
  violation strings.

Provenance: ports of
``crates/agentscope-errors/src/helpers/{overlap,token_jaccard,js_divergence,
claims,luhn,constraints}.rs``.
"""

from __future__ import annotations

import json
import math
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from enum import Enum

__all__ = [
    "normalize",
    "substring_overlap_ratio",
    "verbatim_overlap_ratio",
    "token_jaccard_distinctive",
    "js_divergence",
    "ExtractedAtom",
    "extracted_claims",
    "luhn_valid",
    "violates_declared_constraints",
    "claim_survives_ablation",
    "GateRoute",
    "AblationSignal",
    "route_claim",
]


# ---------------------------------------------------------------------------
# normalize  (formatting-insensitive text canonicalization)
# ---------------------------------------------------------------------------

# Smart-quote / dash / ligature folds → ASCII. A genuine quote copied through a PDF,
# a word-processor, or a chat client picks up these trivial substitutions; folding
# them means a real verbatim span still reads as verbatim post-normalize. (Folds are
# loss-LESS for matching purposes — they only ever make two genuinely-equal spans
# compare equal; they never collapse two distinct claims together.)
_SMART_FOLDS: dict[str, str] = {
    "‘": "'", "’": "'", "‚": "'", "‛": "'",  # single quotes
    "“": '"', "”": '"', "„": '"', "‟": '"',  # double quotes
    "′": "'", "″": '"',                                  # primes
    "‐": "-", "‑": "-", "‒": "-", "–": "-",   # hyphen/dashes
    "—": "-", "―": "-", "−": "-",                  # em/minus
    "…": "...",                                               # ellipsis
    " ": " ", " ": " ", " ": " ", " ": " ",   # nbsp / thin spaces
    "ﬀ": "ff", "ﬁ": "fi", "ﬂ": "fl",              # ligatures
}
_SMART_TABLE = str.maketrans(_SMART_FOLDS)
_WS_RE = re.compile(r"\s+")


def normalize(text: str) -> str:
    """Canonicalize ``text`` for formatting-insensitive verbatim matching.

    Applies, in order: Unicode NFKC, smart-quote/dash/ligature folding to ASCII,
    line-break → space folding, whitespace-run collapse to a single space, lowercase,
    and edge-trim. The result is what "verbatim, modulo trivial formatting" means here:
    a span copied from the document survives a round-trip through a PDF / word-processor
    / chat client and still compares EQUAL to its source.

    This is deliberately *loss-conservative*: it only ever erases formatting noise that
    cannot change which claim a span asserts, so it can make a real quote read as
    verbatim but can NEVER make two semantically-distinct spans collide.
    """
    if not text:
        return ""
    t = unicodedata.normalize("NFKC", text)
    t = t.translate(_SMART_TABLE)
    t = _WS_RE.sub(" ", t)  # folds line-breaks + tabs + runs into single spaces
    return t.strip().lower()


# ---------------------------------------------------------------------------
# substring_overlap_ratio  (port of overlap.rs)
# ---------------------------------------------------------------------------

#: Minimum substring length to count toward "distinctive" overlap. Per R-ERRORS
#: §3.1: 10 characters is short enough to catch quoted phrases but long enough to
#: avoid noise. Matches `MIN_LEN` in overlap.rs.
_MIN_LEN = 10


def _distinctive_substrings(s: str) -> set[str]:
    """Word-boundary-agnostic sliding windows of length ``_MIN_LEN``.

    Emits every overlapping length-``_MIN_LEN`` character window that contains at
    least one alphanumeric character (skips all-whitespace / punctuation-only
    windows). Deduplicated via the set. Mirrors `distinctive_substrings` in
    overlap.rs, including its character-level (not byte-level) windowing.
    """
    chars = list(s)
    out: set[str] = set()
    if len(chars) < _MIN_LEN:
        return out
    for i in range(len(chars) - _MIN_LEN + 1):
        window = "".join(chars[i : i + _MIN_LEN])
        if any(c.isalnum() for c in window):
            out.add(window)
    return out


def substring_overlap_ratio(claim: str, evidence: str) -> float:
    """Fraction of ``claim``'s distinctive 10+ char substrings appearing in ``evidence``.

    Case-insensitive, character-level. Returns a value in ``[0, 1]``:

      * ``1.0`` — every distinctive substring of ``claim`` is present verbatim in
        ``evidence`` (e.g. ``claim`` is a substring of ``evidence``).
      * ``~0.0`` — ``claim``'s distinctive content does not appear in ``evidence``
        (the fabrication signal: a quote that is not actually in the document).

    Empty inputs, or a ``claim`` shorter than the minimum window, yield ``0.0``.
    Port of `substring_overlap_ratio` in overlap.rs.
    """
    if not claim or not evidence:
        return 0.0
    s_lower = claim.lower()
    t_lower = evidence.lower()
    s_subs = _distinctive_substrings(s_lower)
    if not s_subs:
        return 0.0
    matches = sum(1 for sub in s_subs if sub in t_lower)
    return matches / len(s_subs)


def verbatim_overlap_ratio(claim: str, evidence: str) -> float:
    """``substring_overlap_ratio`` computed over :func:`normalize`-d text.

    Identical to :func:`substring_overlap_ratio` except both sides are canonicalized
    first, so a genuine quote that differs from the document only in formatting (smart
    quotes, a folded line-break, a doubled space, an em-dash) still scores ``1.0``.

    This is the overlap the *new* ablation gate uses: it strictly DOMINATES the raw
    ratio (``verbatim_overlap_ratio >= substring_overlap_ratio`` always), so switching
    to it can only ever turn a borderline-genuine quote MORE present — it can never make
    a present quote look absent, preserving the no-false-withhold invariant.
    """
    return substring_overlap_ratio(normalize(claim), normalize(evidence))


# ---------------------------------------------------------------------------
# claim_survives_ablation  (the ablation gate — Soren's idea)
# ---------------------------------------------------------------------------

#: A cited quote is treated as "verbatim-present" (post-normalize) when this fraction
#: or more of its distinctive windows appear in the normalized document. A genuinely
#: copied span scores 1.0; the threshold leaves headroom for a stray window so a real
#: quote with one odd character still counts as present.
_VERBATIM_PRESENT_FLOOR = 0.95

#: After ablating the cited span, the claim's *own* distinctive content is re-checked
#: against the remaining document. The claim "survives" when this much of it is still
#: grounded elsewhere — i.e. the claim did NOT hang entirely on the one gifted span.
#: A modest floor: any non-trivial independent corroboration counts as survival, so the
#: gate routes to the judge only when the claim is *genuinely* single-sourced.
_ABLATION_SURVIVAL_FLOOR = 0.5


def _ablate_first_occurrence(doc_norm: str, quote_norm: str) -> str:
    """Remove the first occurrence of ``quote_norm`` from ``doc_norm`` (both normalized).

    Falls back to removing the longest contiguous run of the quote's distinctive
    windows when the full span is not a single contiguous substring (e.g. the quote
    spans a couple of windows that each appear). Returns the doc unchanged if nothing
    can be located — in which case the caller has already established non-presence.
    """
    idx = doc_norm.find(quote_norm)
    if idx != -1:
        return doc_norm[:idx] + " " + doc_norm[idx + len(quote_norm):]
    # Quote not contiguous: ablate every present distinctive window of the quote.
    out = doc_norm
    for window in _distinctive_substrings(quote_norm):
        pos = out.find(window)
        if pos != -1:
            out = out[:pos] + " " + out[pos + len(window):]
    return out


def claim_survives_ablation(claim: str, evidence_quote: str, document: str) -> bool:
    """Does ``claim`` remain supported by ``document`` AFTER the cited span is removed?

    The ablation test (necessary-not-sufficient grounding):

      1. Require ``evidence_quote`` to be **verbatim-present** in ``document`` post
         :func:`normalize` (overlap ≥ ``_VERBATIM_PRESENT_FLOOR``). If the quote is NOT
         present, there is nothing to ablate — return ``True`` (do NOT claim survival on
         a missing span; the absent-quote case is handled by the routing layer, which
         escalates it — ablation must never be the thing that withholds).
      2. REMOVE that span from the document.
      3. Re-check the **claim's own** distinctive-substring support against the ablated
         document (``verbatim_overlap_ratio(claim, ablated)``).

    Returns ``True`` (**survives**) when the claim is still grounded elsewhere — the
    quote was corroboration, not the sole crutch ⇒ confidently supported. Returns
    ``False`` (**does not survive**) when the claim hung ENTIRELY on the one gifted span
    — ambiguous (a genuine single-source quote OR a copy-a-real-span fabrication) ⇒ the
    caller MUST route it to the LLM-judge for the real call. This function never decides
    payment; it only separates "confidently grounded" from "needs the judge".
    """
    if not claim or not evidence_quote or not document:
        return True  # nothing to ablate / degenerate input → never withhold here
    doc_norm = normalize(document)
    quote_norm = normalize(evidence_quote)
    if not quote_norm:
        return True
    # 1. Quote must actually be present to be ablatable.
    if substring_overlap_ratio(quote_norm, doc_norm) < _VERBATIM_PRESENT_FLOOR:
        return True  # absent span: not our call — routing escalates it, we don't withhold
    # 2 + 3. Ablate the span, re-check the claim's independent support.
    ablated = _ablate_first_occurrence(doc_norm, quote_norm)
    residual = substring_overlap_ratio(normalize(claim), ablated)
    return residual >= _ABLATION_SURVIVAL_FLOOR


# ---------------------------------------------------------------------------
# route_claim  (the deterministic gate IN FRONT of the LLM-judge)
# ---------------------------------------------------------------------------


class GateRoute(str, Enum):
    """How the deterministic gate routes a claim relative to the LLM-judge.

    The gate is **necessary-not-sufficient** and NEVER auto-withholds: every route
    still goes to (or is confirmed by) the judge. The route only annotates *how much*
    deterministic corroboration the cited quote carries.

      * ``SUPPORTED``  — quote verbatim-present AND survives ablation: the claim is
        grounded in more than the one cited span ⇒ confidently supported (the judge
        confirms; may pass cheaply). No penalty, no escalation.
      * ``JUDGE``      — quote verbatim-present but FAILS ablation: the claim hangs on
        exactly that one span (genuine single-source OR copy-a-real-span fabrication) ⇒
        flagged, sent to the judge. No confidence penalty, no auto-withhold.
      * ``ESCALATE``   — quote ABSENT even after normalization: the model cited a span
        that is not in the document ⇒ confidence penalty + ``needs_human`` + STILL run
        the judge. Never an auto-flip to unsupported / $0.
    """

    SUPPORTED = "supported"
    JUDGE = "judge"
    ESCALATE = "escalate"


@dataclass(frozen=True, slots=True)
class AblationSignal:
    """The deterministic gate's read-only verdict on one (claim, quote, document).

    Pure data — carries no payment authority. ``route`` says where the claim goes;
    the numeric fields are surfaced on ``ClaimVerdict`` for auditability.
    """

    route: GateRoute
    overlap: float            # raw substring_overlap_ratio(quote, document) in [0,1]
    verbatim_overlap: float   # normalize-aware overlap(quote, document) in [0,1]
    jaccard: float            # distinctive-token jaccard(quote, document) in [0,1]
    ablation_survived: bool   # claim still supported after the span is ablated
    normalized: bool          # True when normalization was needed to reach verbatim

    @property
    def is_present(self) -> bool:
        return self.verbatim_overlap >= _VERBATIM_PRESENT_FLOOR


def route_claim(claim: str, evidence_quote: str | None, document: str) -> AblationSignal:
    """Compute the deterministic route for one claim BEFORE the LLM-judge runs.

    Pure + total (never raises on ordinary input), deterministic. Encodes the routing
    table from :class:`GateRoute`:

      verbatim-present + survives-ablation → ``SUPPORTED``
      verbatim-present + fails-ablation    → ``JUDGE``
      non-verbatim (absent post-normalize) → ``ESCALATE``

    A missing quote (``None``/empty) routes to ``ESCALATE`` (a finding must cite text).
    This function ONLY classifies; it sets no verdict and moves no money — the caller
    applies the safe (penalize/escalate/route, never auto-withhold) actions.
    """
    quote = evidence_quote or ""
    raw_overlap = substring_overlap_ratio(quote, document)
    vbatim = verbatim_overlap_ratio(quote, document)
    jacc = token_jaccard_distinctive(quote, document)
    # "normalized" == normalization was load-bearing: the span only reads as verbatim
    # AFTER folding formatting (raw overlap fell short, normalized cleared the floor).
    normalized = bool(quote) and vbatim >= _VERBATIM_PRESENT_FLOOR and raw_overlap < _VERBATIM_PRESENT_FLOOR

    if not quote or vbatim < _VERBATIM_PRESENT_FLOOR:
        return AblationSignal(
            route=GateRoute.ESCALATE,
            overlap=raw_overlap,
            verbatim_overlap=vbatim,
            jaccard=jacc,
            ablation_survived=False,
            normalized=normalized,
        )

    survived = claim_survives_ablation(claim, quote, document)
    return AblationSignal(
        route=GateRoute.SUPPORTED if survived else GateRoute.JUDGE,
        overlap=raw_overlap,
        verbatim_overlap=vbatim,
        jaccard=jacc,
        ablation_survived=survived,
        normalized=normalized,
    )


# ---------------------------------------------------------------------------
# token_jaccard_distinctive  (port of token_jaccard.rs)
# ---------------------------------------------------------------------------

#: Curated top-100 English stoplist (the highest-frequency function words). Matches
#: STOPLIST in token_jaccard.rs verbatim.
_STOPLIST: frozenset[str] = frozenset(
    {
        "the", "and", "of", "to", "a", "in", "is", "it", "you", "that", "he", "was",
        "for", "on", "are", "as", "with", "his", "they", "i", "at", "be", "this",
        "have", "from", "or", "one", "had", "by", "words", "but", "not", "what",
        "all", "were", "we", "when", "your", "can", "said", "there", "use", "an",
        "each", "which", "she", "do", "how", "their", "if", "will", "up", "other",
        "about", "out", "many", "then", "them", "these", "so", "some", "her",
        "would", "make", "like", "him", "into", "time", "has", "look", "two", "more",
        "write", "go", "see", "number", "no", "way", "could", "people", "my", "than",
        "first", "water", "been", "call", "who", "its", "now", "find", "long",
        "down", "day", "did", "get", "come", "made", "may", "part",
    }
)

#: Split on any run of non-alphanumeric characters (mirrors Rust's
#: ``split(|c| !c.is_alphanumeric())``). `\W` would keep underscores; `[^...]` here
#: keeps only Unicode letters and digits as token characters.
_TOKEN_SPLIT_RE = re.compile(r"[^0-9A-Za-z]+")


def _tokenize_distinctive(text: str) -> set[str]:
    """Lowercase, split on non-alphanumerics, drop stoplist + tokens shorter than 2.

    Mirrors `tokenize_distinctive` in token_jaccard.rs.
    """
    out: set[str] = set()
    for tok in _TOKEN_SPLIT_RE.split(text.lower()):
        if len(tok) >= 2 and tok not in _STOPLIST:
            out.add(tok)
    return out


def token_jaccard_distinctive(a: str, b: str) -> float:
    """Jaccard similarity over distinctive tokens (top-100 stopwords filtered).

    ``|A ∩ B| / |A ∪ B|`` over the distinctive (non-stopword, len≥2) token sets of
    ``a`` and ``b``. Case-insensitive. Returns ``0.0`` when either distinctive set
    is empty. Port of `token_jaccard_distinctive` in token_jaccard.rs.
    """
    tokens_a = _tokenize_distinctive(a)
    tokens_b = _tokenize_distinctive(b)
    if not tokens_a or not tokens_b:
        return 0.0
    intersection = len(tokens_a & tokens_b)
    union = len(tokens_a | tokens_b)
    if union == 0:
        return 0.0
    return intersection / union


# ---------------------------------------------------------------------------
# js_divergence  (port of js_divergence.rs, term-distribution form)
# ---------------------------------------------------------------------------

#: Smoothing epsilon for zero-probability events — avoids log(0). Matches EPSILON
#: in js_divergence.rs.
_EPSILON = 1e-10


def _term_counts(text: str) -> Counter[str]:
    """Distinctive-term frequency distribution for a text (reuses the tokenizer).

    The Rust helper computes JS divergence between two *count distributions* (span
    name frequencies pulled from SQL). Here the analogue is the term-frequency
    distribution of each text's distinctive tokens, so ``js_divergence(a, b)``
    measures how far ``a``'s vocabulary distribution diverges from ``b``'s.
    """
    counts: Counter[str] = Counter()
    for tok in _TOKEN_SPLIT_RE.split(text.lower()):
        if len(tok) >= 2 and tok not in _STOPLIST:
            counts[tok] += 1
    return counts


def _js_divergence_counts(
    p_counts: Counter[str], q_counts: Counter[str]
) -> float:
    """JS divergence (base-2 log) between two count distributions.

    ``JS(P || Q) = 0.5*KL(P||M) + 0.5*KL(Q||M)`` with ``M = 0.5*(P+Q)``. Direct
    port of the private `js_divergence` in js_divergence.rs — same key-union loop,
    same epsilon guards, base-2 logs (result in ``[0, 1]``).
    """
    p_total = sum(p_counts.values())
    q_total = sum(q_counts.values())
    if p_total == 0 or q_total == 0:
        return 0.0
    keys = set(p_counts) | set(q_counts)
    kl_p_m = 0.0
    kl_q_m = 0.0
    for k in keys:
        p = p_counts.get(k, 0) / p_total
        q = q_counts.get(k, 0) / q_total
        m = 0.5 * (p + q)
        if m > _EPSILON:
            if p > _EPSILON:
                kl_p_m += p * math.log2(p / m)
            if q > _EPSILON:
                kl_q_m += q * math.log2(q / m)
    return 0.5 * (kl_p_m + kl_q_m)


def js_divergence(a: str, b: str) -> float:
    """Jensen-Shannon divergence between the term distributions of ``a`` and ``b``.

    Returns a value in ``[0, 1]`` (base-2 log):

      * ``0.0`` — identical term distributions → *low* penalty (the texts say the
        same things in the same proportions).
      * ``1.0`` — fully disjoint vocabularies → *high* penalty (divergent).

    Empty distributions on either side yield ``0.0`` (no signal). Built on the
    base-2 KL/JS math ported from js_divergence.rs.
    """
    return _js_divergence_counts(_term_counts(a), _term_counts(b))


# ---------------------------------------------------------------------------
# extracted_claims  (port of claims.rs)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ExtractedAtom:
    """One atomic fact extracted from text.

    ``kind`` ∈ {``date``, ``number``, ``currency``, ``entity``, ``url``, ``path``};
    ``literal`` is the verbatim matched span. ``is_specific_fact`` is always ``True``
    (every regex here intentionally captures only concrete factual claims). Mirrors
    the ``Claim`` struct in claims.rs (with currency split out of numeric as its own
    kind, per the target deliverable's atom kinds).
    """

    kind: str
    literal: str
    is_specific_fact: bool = True

    @property
    def summary(self) -> str:
        lit = self.literal if len(self.literal) <= 60 else self.literal[:60] + "…"
        return f"{self.kind}: {lit}"


# ISO date or "DD Mon YYYY" month-name date. Port of the Date pattern in claims.rs.
_RE_DATE = re.compile(
    r"\b(?:\d{4}-\d{2}-\d{2}|\d{1,2} "
    r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]* \d{4})\b"
)
# Currency-formatted number (split out as its own atom kind).
_RE_CURRENCY = re.compile(r"\$\d+(?:,\d{3})*(?:\.\d+)?")
# Number with a unit OR a percentage (currency handled separately above). The Rust
# numeric pattern is case-insensitive on the unit suffix (MB == mb).
_RE_NUMBER = re.compile(
    r"\b\d+(?:\.\d+)?\s*(?:ms|s|m|h|d|kb|mb|gb|tb|kg|mg|cm|mm|km|%)\b",
    re.IGNORECASE,
)
# 2+ consecutive Capitalized words (excludes single names + acronyms). Port of the
# NamedEntity pattern in claims.rs.
_RE_ENTITY = re.compile(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+\b")
# URLs. Port of the Url pattern in claims.rs.
_RE_URL = re.compile(r"\bhttps?://[A-Za-z0-9._~:/?#\[\]@!$&'()*+,;=%-]+")
# File paths: /…, ~/…, ./…, or X:\… (Windows). Port of the FilePath pattern.
_RE_PATH = re.compile(r"(?:^|\s)((?:/|~/|\./|[A-Za-z]:\\)[A-Za-z0-9._/\\-]+)")

# Ordered (kind, regex) — same evaluation order as compile_patterns() in claims.rs,
# with currency inserted right after date so a "$…" span is classified as currency.
_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("date", _RE_DATE),
    ("currency", _RE_CURRENCY),
    ("number", _RE_NUMBER),
    ("entity", _RE_ENTITY),
    ("url", _RE_URL),
    ("path", _RE_PATH),
)


def extracted_claims(text: str) -> list[ExtractedAtom]:
    """Extract atomic facts from ``text`` via deterministic regex (NOT an LLM).

    Returns ``ExtractedAtom``s for dates, numbers (with units / percentages),
    currency, named entities, URLs, and file paths — the concrete, groundable
    statements about external reality. Order follows the pattern order (all dates,
    then currency, then numbers, …), matching the Rust helper. Port of
    `extracted_claims` in claims.rs.
    """
    out: list[ExtractedAtom] = []
    for kind, pattern in _PATTERNS:
        for m in pattern.finditer(text):
            # The path pattern captures the path in group 1 (after an optional
            # leading space); everything else matches the literal directly.
            literal = (m.group(1) if kind == "path" else m.group(0)).strip()
            if literal:
                out.append(ExtractedAtom(kind=kind, literal=literal))
    return out


# ---------------------------------------------------------------------------
# luhn_valid  (port of luhn.rs)
# ---------------------------------------------------------------------------


def luhn_valid(number: str) -> bool:
    """Standard Luhn (mod-10) checksum over the digits of ``number``.

    Returns ``True`` iff the digit-only stripped form has 13–19 digits and passes
    the Luhn check (filters random 16-digit sequences that are not real card
    numbers). Non-digit / out-of-range inputs return ``False``. Port of `luhn_check`
    in luhn.rs.
    """
    digits = [int(c) for c in number if c.isdigit()]
    if not 13 <= len(digits) <= 19:
        return False
    total = 0
    for i, d in enumerate(reversed(digits)):
        if i % 2 == 1:
            doubled = d * 2
            total += doubled - 9 if doubled > 9 else doubled
        else:
            total += d
    return total % 10 == 0


# ---------------------------------------------------------------------------
# violates_declared_constraints  (port of constraints.rs)
# ---------------------------------------------------------------------------

_RE_WORD_LIMIT = re.compile(
    r"(?:in|under|no more than|at most|keep it under)\s+(\d+)\s+words?"
)
_RE_CHAR_LIMIT = re.compile(
    r"(?:in|under|no more than|at most)\s+(\d+)\s+characters?"
)


def _extract_word_limit(s: str) -> int | None:
    m = _RE_WORD_LIMIT.search(s)
    return int(m.group(1)) if m else None


def _extract_char_limit(s: str) -> int | None:
    m = _RE_CHAR_LIMIT.search(s)
    return int(m.group(1)) if m else None


def violates_declared_constraints(output: str, rubric: str) -> list[str]:
    """Check ``output`` against length / format constraints declared in ``rubric``.

    The Rust helper returns a single ``bool``; this port returns the *list* of
    concrete violation strings (empty list == no violation == the Rust ``false``),
    so callers can surface exactly which declared constraint was broken. Recognized
    constraints (case-insensitive, scanned in ``rubric``):

      * **Word limit** — ``"in N words or less"`` / ``"keep it under N words"`` /
        ``"at most N words"`` → violated when ``output`` has more than ``N``
        whitespace-delimited words.
      * **Character limit** — ``"no more than N characters"`` etc. → violated when
        ``output`` is longer than ``N`` characters.
      * **JSON format** — ``"as JSON"`` / ``"in JSON"`` → violated when ``output``
        does not parse as JSON.

    Port of `violates_declared_constraints` in constraints.rs.
    """
    violations: list[str] = []
    lower = rubric.lower()

    max_words = _extract_word_limit(lower)
    if max_words is not None:
        actual = len(output.split())
        if actual > max_words:
            violations.append(
                f"word-limit: declared ≤{max_words} words, output has {actual}"
            )

    max_chars = _extract_char_limit(lower)
    if max_chars is not None:
        actual_chars = len(output)
        if actual_chars > max_chars:
            violations.append(
                f"char-limit: declared ≤{max_chars} characters, output has {actual_chars}"
            )

    if "as json" in lower or "in json" in lower:
        try:
            json.loads(output)
        except (json.JSONDecodeError, ValueError):
            violations.append('format: rubric requires JSON, output is not valid JSON')

    return violations
