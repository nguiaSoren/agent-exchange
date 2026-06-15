"""Seeded-liar catch-rate tests — all OFFLINE, deterministic confusion matrix.

We inject KNOWN-labelled claims (some FABRICATED, some GENUINE) and drive the real
`Verifier` with a backend that returns a CHOSEN verdict for each claim, so the resulting
confusion matrix is fixed and the catch-rate arithmetic can be asserted exactly.

The trick: `MockBackend` returns one fixed reply for every call, but `verify()` sends ALL
the claims for one contract in a single call and expects a JSON array (one object per
claim, in order). To get a per-claim verdict regardless of how `run_catch_rate` batches
claims, we use a tiny `_ScriptedBackend` that reads the claims out of the user message
(`build_user_message` numbers them verbatim) and emits the verdict we scripted for each.

Confusion matrix (positive class = FABRICATED / should-withhold; `unsupported` = withhold):
  tp = FABRICATED → unsupported   (lie caught)
  fn = FABRICATED → confirmed     (lie missed)
  fp = GENUINE    → unsupported    (good work wrongly withheld)
  tn = GENUINE    → confirmed      (good work let through)

Run:  PYTHONHASHSEED=1 .venv/bin/python tests/test_catch_rate.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from agent_exchange.core import CompletionResult, Message, MockBackend, Usage
from agent_exchange.core.backend import ModelBackend
from agent_exchange.eval.catch_rate import format_report, run_catch_rate
from agent_exchange.eval.seeded_liar import (
    gold_claims_from_calibration,
    load_fixture,
    save_fixture,
)
from agent_exchange.eval.types import FABRICATED, GENUINE, LabeledClaim
from agent_exchange.verify import Verifier

_CALIB_CASES = os.path.join(
    os.path.dirname(__file__), "..", "data", "calibration", "cases.json"
)


# ── a backend that emits a scripted verdict per claim ──

class _ScriptedBackend(ModelBackend):
    """Returns, for each claim found in the user message, the verdict scripted for that
    claim text. `verdicts` maps claim-text → (verdict, confidence). Order is recovered
    from the numbered CLAIMS block that `build_user_message` writes verbatim."""

    def __init__(self, verdicts: dict[str, tuple[str, float]]):
        self._verdicts = verdicts

    def _claims_in_order(self, messages: list[Message]) -> list[str]:
        # The last message is the user turn; claims are numbered "N. <claim>" lines
        # (see build_user_message). Parse those lines exactly — substring matching would
        # collide on e.g. "...number 1" inside "...number 100".
        user = messages[-1].content
        ordered: list[str] = []
        for line in user.splitlines():
            stripped = line.strip()
            # a claim line looks like "<n>. <claim text>"
            if "." in stripped and stripped.split(".", 1)[0].isdigit():
                candidate = stripped.split(".", 1)[1].strip()
                if candidate in self._verdicts:
                    ordered.append(candidate)
        return ordered

    async def complete(
        self,
        messages: list[Message],
        *,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> CompletionResult:
        ordered = self._claims_in_order(messages)
        items = []
        for claim in ordered:
            verdict, conf = self._verdicts[claim]
            quote = None if verdict == "unsupported" else "scripted evidence span"
            items.append(
                {
                    "verdict": verdict,
                    "confidence": conf,
                    "reason": f"scripted {verdict}",
                    "evidence_quote": quote,
                }
            )
        usage = Usage(1, 1, 2, estimated_cost_usd=0.0)
        return CompletionResult(
            text=json.dumps(items),
            model="scripted",
            provider="mock",
            usage=usage,
            submission_ns=0,
            return_ns=1,
            finish_reason="stop",
        )


def _run(cases, verdicts, **kw):
    backend = _ScriptedBackend(verdicts)
    return asyncio.run(run_catch_rate(cases, Verifier(backend), **kw))


# Each claim gets a UNIQUE contract so any batching strategy (per-claim or per-contract)
# still pairs the right verdict with the right claim.
def _mk(label: str, idx: int) -> LabeledClaim:
    tag = "lie" if label == FABRICATED else "true"
    return LabeledClaim(
        contract=f"Contract {idx}: clause text for {tag} case {idx}.",
        claim=f"{tag} claim number {idx}",
        label=label,
        source="audit",
    )


# ── the headline: an exact confusion matrix ──

def test_confusion_matrix_is_exact():
    # 3 fabricated caught (tp), 1 fabricated missed (fn),
    # 4 genuine let through (tn), 2 genuine wrongly withheld (fp).
    cases: list[LabeledClaim] = []
    verdicts: dict[str, tuple[str, float]] = {}

    def add(label, verdict, n, start):
        for i in range(start, start + n):
            c = _mk(label, i)
            cases.append(c)
            verdicts[c.claim] = (verdict, 0.9)

    add(FABRICATED, "unsupported", 3, 0)   # tp = 3
    add(FABRICATED, "confirmed", 1, 100)   # fn = 1
    add(GENUINE, "confirmed", 4, 200)      # tn = 4
    add(GENUINE, "unsupported", 2, 300)    # fp = 2

    rep = _run(cases, verdicts)

    assert rep.n_total == 10
    assert rep.n_fabricated == 4 and rep.n_genuine == 6
    assert (rep.tp, rep.fn, rep.fp, rep.tn) == (3, 1, 2, 4)

    # the three headline rates, derived from the matrix
    assert abs(rep.catch_rate - 3 / (3 + 1)) < 1e-9            # tp/(tp+fn) = 0.75
    assert abs(rep.false_withhold_rate - 2 / (2 + 4)) < 1e-9   # fp/(fp+tn) = 0.333..
    assert abs(rep.precision - 3 / (3 + 2)) < 1e-9             # tp/(tp+fp) = 0.6
    print(f"    matrix tp/fp/tn/fn = {rep.tp}/{rep.fp}/{rep.tn}/{rep.fn}")


def test_partial_counts_as_let_through_for_genuine():
    # A 'partial' verdict is NOT 'unsupported', so a GENUINE claim marked partial is a
    # tn (let through), and a FABRICATED claim marked partial is a fn (missed).
    cases = [_mk(GENUINE, 1), _mk(FABRICATED, 2)]
    verdicts = {
        cases[0].claim: ("partial", 0.8),
        cases[1].claim: ("partial", 0.8),
    }
    rep = _run(cases, verdicts)
    assert (rep.tp, rep.fp, rep.tn, rep.fn) == (0, 0, 1, 1)


# ── a perfect verifier ──

def test_perfect_verifier():
    cases = [_mk(FABRICATED, i) for i in range(5)] + [_mk(GENUINE, 100 + i) for i in range(5)]
    verdicts = {}
    for c in cases:
        verdicts[c.claim] = ("unsupported" if c.label == FABRICATED else "confirmed", 0.95)
    rep = _run(cases, verdicts)
    assert rep.catch_rate == 1.0
    assert rep.false_withhold_rate == 0.0
    assert rep.tp == 5 and rep.tn == 5 and rep.fp == 0 and rep.fn == 0
    assert rep.precision == 1.0


def test_worst_verifier_catches_nothing():
    # all fabricated confirmed (every lie missed), all genuine confirmed
    cases = [_mk(FABRICATED, i) for i in range(3)] + [_mk(GENUINE, 100 + i) for i in range(3)]
    verdicts = {c.claim: ("confirmed", 0.9) for c in cases}
    rep = _run(cases, verdicts)
    assert rep.catch_rate == 0.0
    assert rep.tp == 0 and rep.fn == 3
    assert rep.false_withhold_rate == 0.0  # nothing withheld → no false withholds


# ── gold from the calibration set ──

def test_gold_claims_from_calibration():
    gold = gold_claims_from_calibration(_CALIB_CASES)
    assert len(gold) == 24
    assert all(isinstance(g, LabeledClaim) for g in gold)
    # gold='unsupported' → FABRICATED;  gold in {confirmed, partial} → GENUINE
    by_claim = {g.claim: g for g in gold}
    # c02 invents a dollar figure → unsupported → FABRICATED
    c02 = next(g for g in gold if "capped at $1,000,000" in g.claim)
    assert c02.label == FABRICATED
    # c01 clean restatement → confirmed → GENUINE
    c01 = next(g for g in gold if g.claim == "Liability is capped at the fees paid in the prior 12 months.")
    assert c01.label == GENUINE
    # c04 'all damages' → partial → GENUINE (partial is grounded, not a fabrication)
    c04 = next(g for g in gold if g.claim == "Vendor disclaims liability for all damages.")
    assert c04.label == GENUINE
    # counts: gold has 12 unsupported, 8 confirmed, 4 partial → 12 FABRICATED / 12 GENUINE
    n_fab = sum(g.label == FABRICATED for g in gold)
    n_gen = sum(g.label == GENUINE for g in gold)
    assert n_fab == 12 and n_gen == 12
    assert n_fab + n_gen == len(gold)
    # every claim carries the calibration provenance
    assert all(g.source for g in gold)
    print(f"    gold: {n_fab} fabricated / {n_gen} genuine")


# ── fixture round-trip ──

def test_fixture_roundtrip():
    claims = [
        LabeledClaim("contract A", "claim a", FABRICATED, "llm_liar"),
        LabeledClaim("contract B", "claim b", GENUINE, "llm_genuine"),
        LabeledClaim("contract C", "claim c", FABRICATED, "gold"),
    ]
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "fixture.json")
        save_fixture(claims, path)
        assert os.path.exists(path)
        loaded = load_fixture(path)
    assert loaded == claims
    assert all(isinstance(c, LabeledClaim) for c in loaded)
    assert [c.label for c in loaded] == [FABRICATED, GENUINE, FABRICATED]


# ── the formatted report ──

def test_format_report_runs_and_mentions_catch_rate():
    cases = [_mk(FABRICATED, 0), _mk(GENUINE, 100)]
    verdicts = {cases[0].claim: ("unsupported", 0.9), cases[1].claim: ("confirmed", 0.9)}
    rep = _run(cases, verdicts)
    text = format_report(rep)
    assert isinstance(text, str) and text
    assert "catch" in text.lower()


# ── the MockBackend sanity-check (matches tests/test_verifier.py style) ──

def test_scripted_backend_via_plain_mock_for_one_contract():
    """Sanity: a single fixed-reply MockBackend drives a known matrix when all claims
    share one contract+call (the simplest possible seeded-liar shape)."""
    reply = json.dumps([
        {"verdict": "unsupported", "confidence": 0.9, "reason": "lie", "evidence_quote": None},
        {"verdict": "confirmed", "confidence": 0.9, "reason": "true", "evidence_quote": "x"},
    ])
    vs = asyncio.run(
        Verifier(MockBackend(reply=reply)).verify("contract", ["lie claim", "true claim"])
    )
    assert vs[0].verdict.value == "unsupported" and vs[1].verdict.value == "confirmed"


def _run_all():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"  ✓ {fn.__name__}")
    print(f"\n{len(fns)} passed")


if __name__ == "__main__":
    _run_all()
