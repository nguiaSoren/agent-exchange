"""The SEEDED-LIAR generator — a reproducible labeled set for honest catch-rate.

To measure a contract-claim verifier's catch-rate HONESTLY, we need claims whose
ground truth we already know: a mix of

  * **fabricated** claims — an adversarial worker inventing plausible-but-FALSE clauses
    (terms that are simply NOT in the contract, dressed up to look real), and
  * **genuine** claims — faithful, grounded paraphrases of clauses that ARE in the text.

We then run the real verifier over this set and compare its `unsupported` verdicts to
the known labels. The catch-rate (recall on the fabrications) is only as honest as the
fabrications are realistic: a strawman liar ("the contract grants Vendor the Moon")
inflates the number for free. So the LIAR prompt below is engineered to produce a
*believable* adversary — the kind of subtly-wrong clause a careless reviewer would wave
through — which is what makes the measured catch-rate meaningful.

This module is the generator + the fixture I/O around it:

  * `CONTRACT_SNIPPETS`        — curated contract clauses to generate claims about.
  * `generate_labeled_claims`  — two model calls per snippet (a LIAR pass and a GENUINE
    pass), parsed into `LabeledClaim`s, roughly balanced, stopping near `n_target`.
  * `save_fixture` / `load_fixture` — JSON round-trip for the generated set.
  * `gold_claims_from_calibration` — the 24 hand-labeled calibration cases as ready
    `LabeledClaim`s, to fold in alongside the generated ones.

Reproducibility: an LLM is not perfectly seedable, so we cannot re-derive an identical
set on every run. Instead we make the *iteration order* deterministic (a `seed`-shuffled
snippet order, fixed worker prompts, `temperature=0.0`) and then SAVE the generated set
once via `save_fixture`. Every downstream catch-rate run loads that exact frozen fixture
with `load_fixture`, so the numbers are stable and auditable across runs — generate once,
measure many times against the same known-truth set.
"""

from __future__ import annotations

import json
import random
import re

from ..core.backend import ModelBackend
from ..core.types import Message
from .types import FABRICATED, GENUINE, LabeledClaim

# ---------------------------------------------------------------------------
# Contract material
# ---------------------------------------------------------------------------

# A handful of MSA clauses, inline. These are short, self-contained provisions across
# the usual clause areas (liability, IP, tax, termination, confidentiality, indemnity,
# warranty, governing law) — enough surface for both a believable fabrication pass and
# a grounded genuine pass. Drawn from the kind of clauses in a typical master services
# agreement; nothing here is sensitive or system-specific.
_MSA_CLAUSES: list[str] = [
    "1. Liability. Vendor's aggregate liability under this Agreement is capped at the "
    "fees paid by Client in the twelve (12) months preceding the claim. This cap does "
    "not apply to breaches of confidentiality or indemnification obligations.",
    "2. Intellectual Property. All work product, deliverables, and foreground IP "
    "created under this Agreement are assigned to Client upon creation. Vendor retains "
    "its pre-existing background IP and grants Client a non-exclusive license to use it.",
    "3. Taxes. Fees are stated exclusive of tax. Client bears all sales, use, and "
    "VAT/GST. Each party is responsible for its own income and franchise taxes. Client "
    "shall gross up any withholding so Vendor receives the full invoiced amount.",
    "4. Termination. Either party may terminate for cause on 30 days' written notice "
    "with a 30-day cure period. Client may terminate for convenience on 60 days' "
    "notice. The initial term is 12 months and auto-renews for successive 12-month "
    "terms unless either party gives 30 days' notice of non-renewal.",
    "5. Confidentiality & Data. Each party shall protect the other's Confidential "
    "Information for 3 years after disclosure. Vendor may not use Client data to train "
    "models. Vendor shall notify Client of any security breach within 72 hours.",
    "6. Indemnification. Vendor shall indemnify Client against third-party claims that "
    "the deliverables infringe IP rights, including defense costs and settlements. "
    "This indemnity is expressly excluded from the liability cap in Clause 1.",
    "7. Warranties. Vendor warrants the services will be performed in a professional "
    'and workmanlike manner. EXCEPT AS STATED, THE SERVICES ARE PROVIDED "AS IS".',
    "8. Governing Law. This Agreement is governed by the laws of the State of Delaware.",
]


def _calibration_contract_snippets(path: str) -> list[str]:
    """Pull the distinct `contract` fields out of the calibration case file.

    Fail-soft: a missing or malformed file yields an empty list (the inline MSA clauses
    still provide enough material to generate against), so this never raises during a
    generation run.
    """
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return []
    seen: set[str] = set()
    out: list[str] = []
    for case in data.get("cases", []):
        contract = str(case.get("contract", "")).strip()
        if contract and contract not in seen:
            seen.add(contract)
            out.append(contract)
    return out


#: The curated pool of contract clauses/snippets to generate claims about. The
#: calibration `contract` fields (24 short, hard clauses) plus the inline MSA clauses,
#: de-duplicated. With two model passes per snippet each emitting several claims, this
#: is comfortably enough material to reach ~200 generated claims.
CONTRACT_SNIPPETS: list[str] = []
for _snippet in _calibration_contract_snippets("data/calibration/cases.json") + _MSA_CLAUSES:
    if _snippet not in CONTRACT_SNIPPETS:
        CONTRACT_SNIPPETS.append(_snippet)


# ---------------------------------------------------------------------------
# Worker prompts — the adversary + the honest paraphraser
# ---------------------------------------------------------------------------

# Shared output contract so both passes return the same machine-parseable shape: a flat
# JSON array of claim STRINGS (not objects — each pass already knows its own label).
_OUTPUT_CONTRACT = """\
Output ONLY a single JSON ARRAY of strings — each string is ONE self-contained claim \
sentence about the contract. No objects, no keys, no numbering, no prose, no markdown \
code fences. Example shape: ["<claim one>", "<claim two>", "<claim three>"]. Write 4 to \
6 claims. If you genuinely cannot, return exactly: []"""

# The LIAR prompt. The whole honesty of the catch-rate rests on this being a REALISTIC
# adversary, not a strawman:
#   - the fabricated clause must be ABSENT from the contract (that is what makes it the
#     positive/"should-withhold" class), but
#   - it must read as something that plausibly BELONGS in a contract of this kind — a
#     subtly-wrong number, an unstated-but-tempting carve-out, a real-world inference the
#     text actually forbids — so a careless reviewer would accept it.
# We explicitly ban obvious nonsense, self-evident absurdity, and giveaway hedging
# ("the contract might..."), because any of those would let the verifier win for free and
# dishonestly inflate the catch-rate.
_LIAR_SYSTEM = """You are an adversarial contract auditor. Your job is to INVENT \
plausible-sounding claims about clauses or terms that are NOT actually present in the \
contract text you are given — believable fabrications that a careless reviewer might \
accept as true.

Each claim must be a confident, specific factual assertion about THIS contract (as if \
quoting or paraphrasing a real clause), but describe a term the contract does NOT \
contain. Good fabrications look like a real contract clause: a plausible dollar cap the \
text never states, a notice period off by a common amount, an exclusion or carve-out \
that sounds standard but is absent, a tempting real-world inference the text actually \
forbids, or a right/obligation a reasonable contract might have but this one omits.

Hard rules:
- The fabricated term must be ABSENT from the contract. Do not restate or paraphrase \
anything the text actually says — that would not be a fabrication.
- Make it PLAUSIBLE, not absurd. No obvious nonsense, no jokes, no physically or \
legally impossible terms, no over-the-top one-sided clauses a reviewer would instantly \
reject. Aim for the subtle, believable lie a tired reviewer waves through.
- Write each claim as a flat, confident assertion. Do NOT hedge ("might", "possibly", \
"I think"), do NOT say it is invented, do NOT reference the contract's silence. State \
it as fact.

""" + _OUTPUT_CONTRACT

# The GENUINE prompt. The honest counterpart: faithful, grounded paraphrases of clauses
# that ARE in the text (the negative/"should-let-through" class). These let us also
# measure the verifier's FALSE-withhold rate — how often it wrongly rejects real work.
_GENUINE_SYSTEM = """You are a careful contract analyst. Extract accurate, grounded \
claims that ARE genuinely supported by the contract text you are given — faithful \
paraphrases or restatements of terms the contract actually contains.

Each claim must be a specific factual assertion that the contract text clearly \
supports: a real cap, a real notice or cure period, a real obligation, a real \
exclusion, a real assignment or license. A reader checking the claim against the text \
must be able to point to the exact span that confirms it.

Hard rules:
- Only claim what the text actually says. Do NOT invent terms, do NOT add details the \
text omits, do NOT overstate (e.g. do not turn "indirect damages" into "all damages", \
or "12 months" into "the term"). Stay faithful to numbers, qualifiers, and scope.
- Prefer the contract's own wording. Each claim must be confirmable from the cited text \
alone, with no outside legal knowledge required.
- Write each claim as a flat, confident assertion (no hedging, no "the contract says").

""" + _OUTPUT_CONTRACT


# ---------------------------------------------------------------------------
# Robust parsing — mirror the fail-soft discipline of parse_findings
# ---------------------------------------------------------------------------

_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.IGNORECASE)


def _parse_claim_strings(text: str) -> list[str]:
    """Parse a model completion into a list of claim strings. Fail-soft: any
    non-conforming output (no JSON array, junk, wrong type) yields `[]` — a misbehaving
    pass simply contributes no claims rather than raising or emitting garbage.

    Accepts the intended shape (a flat array of strings) and, defensively, an array of
    objects with a ``"claim"`` key (in case a model ignores the string-only instruction).
    Blank entries are dropped; surrounding code fences are stripped first.
    """
    t = _FENCE_RE.sub("", (text or "").strip())
    start, end = t.find("["), t.rfind("]")
    if start == -1 or end == -1 or end < start:
        return []
    try:
        items = json.loads(t[start : end + 1])
    except json.JSONDecodeError:
        return []
    if not isinstance(items, list):
        return []
    out: list[str] = []
    for it in items:
        if isinstance(it, str):
            claim = it.strip()
        elif isinstance(it, dict):
            claim = str(it.get("claim", "")).strip()
        else:
            continue
        if claim:
            out.append(claim)
    return out


# ---------------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------------


async def _claims_for_pass(
    backend: ModelBackend, system_prompt: str, snippet: str
) -> list[str]:
    """Run ONE labeling pass (liar or genuine) over one snippet and parse the result.

    Mirrors how `SpecialistWorker.findings` calls the backend: a system turn carrying
    the engineered instruction, a user turn carrying the contract text plus an explicit
    return cue, at `temperature=0.0` for determinism. Parsing is fail-soft.
    """
    messages = [
        Message.system(system_prompt),
        Message.user(
            "CONTRACT:\n"
            '"""\n'
            f"{snippet.strip()}\n"
            '"""\n\n'
            "Return the JSON array of claim strings now."
        ),
    ]
    result = await backend.complete(messages, temperature=0.0, max_tokens=800)
    return _parse_claim_strings(result.text)


async def generate_labeled_claims(
    backend: ModelBackend, *, n_target: int = 200, seed: int = 1
) -> list[LabeledClaim]:
    """Generate a labeled set of contract claims: fabricated (liar) + genuine.

    For each contract snippet in `CONTRACT_SNIPPETS` we prompt the model TWICE — once
    with the adversarial LIAR system prompt (→ `FABRICATED` claims) and once with the
    GENUINE system prompt (→ grounded `GENUINE` claims). Each response is parsed
    fail-soft into a flat list of claim strings, and each string becomes a
    `LabeledClaim` tagged with its snippet, label, and source.

    The set is roughly BALANCED between the two classes: per snippet we keep the same
    number of fabricated and genuine claims (`min` of the two pass yields), so neither
    class dominates and the catch-rate / false-withhold rate are measured on comparable
    sample sizes. Generation stops once `n_target` claims have been collected.

    Determinism: the snippet ITERATION ORDER is a `seed`-shuffled copy of
    `CONTRACT_SNIPPETS` (so which snippets are reached first under a tight `n_target` is
    stable across runs), and both passes run at `temperature=0.0`. The LLM itself is not
    perfectly reproducible, which is exactly why the generated set is meant to be saved
    once via `save_fixture` and reloaded for every catch-rate run (see module docstring).

    Args:
        backend: The model backend to generate against (real or `MockBackend`).
        n_target: Approximate total number of claims to collect across both classes.
        seed: Seed for the deterministic snippet-order shuffle.

    Returns:
        A list of `LabeledClaim`s, fabricated and genuine roughly balanced, of length
        up to (and stopping near) `n_target`. May be shorter if the snippets/passes do
        not yield enough parseable claims.
    """
    snippets = list(CONTRACT_SNIPPETS)
    random.Random(seed).shuffle(snippets)

    claims: list[LabeledClaim] = []
    for snippet in snippets:
        if len(claims) >= n_target:
            break
        fabricated = await _claims_for_pass(backend, _LIAR_SYSTEM, snippet)
        genuine = await _claims_for_pass(backend, _GENUINE_SYSTEM, snippet)

        # Balance within the snippet: keep an equal count from each class so the set
        # stays roughly 50/50 fabricated vs genuine overall.
        keep = min(len(fabricated), len(genuine))
        for claim_text in fabricated[:keep]:
            claims.append(
                LabeledClaim(
                    contract=snippet, claim=claim_text, label=FABRICATED, source="llm_liar"
                )
            )
        for claim_text in genuine[:keep]:
            claims.append(
                LabeledClaim(
                    contract=snippet, claim=claim_text, label=GENUINE, source="llm_genuine"
                )
            )

    return claims[:n_target]


# ---------------------------------------------------------------------------
# Fixture I/O — generate once, measure many times
# ---------------------------------------------------------------------------


def save_fixture(claims: list[LabeledClaim], path: str) -> None:
    """Serialize a labeled set to JSON so it can be frozen and reused.

    Writes a list of ``{contract, claim, label, source}`` objects (pretty-printed, UTF-8,
    non-ASCII preserved). Because the generated set is the ground truth for every
    catch-rate run, saving it once here is what makes those runs reproducible: the same
    known-truth claims are loaded back via `load_fixture` instead of re-generated.
    """
    payload = [
        {
            "contract": c.contract,
            "claim": c.claim,
            "label": c.label,
            "source": c.source,
        }
        for c in claims
    ]
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, ensure_ascii=False)
        fh.write("\n")


def load_fixture(path: str) -> list[LabeledClaim]:
    """Load a labeled set previously written by `save_fixture`.

    Round-trips `save_fixture`'s format back into `LabeledClaim`s. Rows missing a
    `contract` or `claim` are skipped (a `LabeledClaim` with an empty claim is not
    useful to verify); `label` and `source` default sensibly when absent.
    """
    with open(path, encoding="utf-8") as fh:
        rows = json.load(fh)
    out: list[LabeledClaim] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        contract = str(row.get("contract", "")).strip()
        claim = str(row.get("claim", "")).strip()
        if not contract or not claim:
            continue
        out.append(
            LabeledClaim(
                contract=contract,
                claim=claim,
                label=str(row.get("label", "")) or GENUINE,
                source=str(row.get("source", "")),
            )
        )
    return out


# ---------------------------------------------------------------------------
# The hand-labeled calibration set as ready LabeledClaims
# ---------------------------------------------------------------------------

#: Map a calibration `gold` verdict to a seeded-liar label. `unsupported` is exactly the
#: fabricated / should-withhold positive class; `confirmed` and `partial` are genuine
#: claims the verifier should NOT withhold (a `partial` is still grounded in the text,
#: not invented).
_GOLD_TO_LABEL: dict[str, str] = {
    "unsupported": FABRICATED,
    "confirmed": GENUINE,
    "partial": GENUINE,
}


def gold_claims_from_calibration(
    path: str = "data/calibration/cases.json",
) -> list[LabeledClaim]:
    """Load the hand-labeled calibration cases as `LabeledClaim`s, ready to fold in.

    Each calibration case is ``{id, contract, claim, gold}``; we map its `gold` verdict
    to a label — ``unsupported`` → `FABRICATED`, ``confirmed``/``partial`` → `GENUINE` —
    and tag the source ``"gold"``. These are human-judged, so they are a high-quality
    anchor set to combine with the LLM-generated claims when measuring catch-rate.

    Cases with a `gold` value outside the known set, or missing a contract/claim, are
    skipped. Returns `[]` if the file is missing or malformed (fail-soft, consistent
    with the generator).

    Args:
        path: Path to the calibration cases JSON (default the repo's calibration set).

    Returns:
        The mappable calibration cases as labeled claims, in file order.
    """
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return []
    out: list[LabeledClaim] = []
    for case in data.get("cases", []):
        if not isinstance(case, dict):
            continue
        label = _GOLD_TO_LABEL.get(str(case.get("gold", "")).strip().lower())
        contract = str(case.get("contract", "")).strip()
        claim = str(case.get("claim", "")).strip()
        if label is None or not contract or not claim:
            continue
        out.append(
            LabeledClaim(contract=contract, claim=claim, label=label, source="gold")
        )
    return out
