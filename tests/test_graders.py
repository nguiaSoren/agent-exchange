"""Deterministic grader tests — ported from AgentScope's Rust helper tests + the
verifier-integration cases. All OFFLINE, no network, fully deterministic.

Covers each grader (substring overlap, distinctive-token Jaccard, JS-divergence, atom
extraction, Luhn, declared-constraint checks) against KNOWN values, plus the two
integration invariants that matter:
  * the verifier's deterministic gate SHORT-CIRCUITS a confirmed verdict whose cited
    evidence_quote is not in the document (fabricated span → unsupported, no model
    re-call), and
  * a GENUINE claim whose quote IS in the document is left untouched (no false
    withhold) — and with the gate OFF the verdict is byte-identical to today.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from agent_exchange.core import MockBackend
from agent_exchange.verify import Verifier
from agent_exchange.verify.graders import (
    ExtractedAtom,
    GateRoute,
    claim_survives_ablation,
    extracted_claims,
    js_divergence,
    luhn_valid,
    normalize,
    route_claim,
    substring_overlap_ratio,
    token_jaccard_distinctive,
    verbatim_overlap_ratio,
    violates_declared_constraints,
)
from agent_exchange.verify.schema import Verdict

_CALIB = os.path.join(os.path.dirname(__file__), "..", "data", "calibration", "cases.json")
_FIXTURE = os.path.join(os.path.dirname(__file__), "..", "data", "eval", "seeded_liar_fixture.json")


# ── substring_overlap_ratio (port of overlap.rs tests) ──

def test_overlap_identical_is_one():
    r = substring_overlap_ratio("the quick brown fox jumps", "the quick brown fox jumps")
    assert abs(r - 1.0) < 1e-9


def test_overlap_disjoint_near_zero():
    r = substring_overlap_ratio("alpha beta gamma delta", "completely separate content here")
    assert r < 0.2


def test_overlap_case_insensitive():
    assert abs(substring_overlap_ratio("HELLO WORLD AGAIN", "hello world again") - 1.0) < 1e-9


def test_overlap_empty_inputs_zero():
    assert substring_overlap_ratio("", "anything") == 0.0
    assert substring_overlap_ratio("anything", "") == 0.0
    assert substring_overlap_ratio("", "") == 0.0


def test_overlap_short_input_below_min_len_zero():
    assert substring_overlap_ratio("abc", "abc") == 0.0  # below the 10-char window


def test_overlap_substring_present_full_match():
    # The whole claim is a verbatim span of the document → every window matches.
    quote = "fees paid in the prior 12 months"
    doc = "7.1 Vendor's liability is capped at the fees paid in the prior 12 months."
    assert abs(substring_overlap_ratio(quote, doc) - 1.0) < 1e-9


def test_overlap_deterministic():
    s = "The fox jumped over the lazy dog at midnight"
    t = "Earlier that day, the fox jumped over the lazy dog"
    assert substring_overlap_ratio(s, t) == substring_overlap_ratio(s, t)


# ── token_jaccard_distinctive (port of token_jaccard.rs tests) ──

def test_jaccard_identical_is_one():
    assert abs(token_jaccard_distinctive("fetch user records", "fetch user records") - 1.0) < 1e-9


def test_jaccard_only_stopwords_is_zero():
    assert token_jaccard_distinctive("the and of to", "in is a was") == 0.0


def test_jaccard_distinctive_overlap_dominates():
    # distinctive_a = {please, fetch, user, records, database}
    # distinctive_b = {fetch, records}  ("would"/"like" are stopwords)
    # intersection = 2, union = 5 → 0.4
    r = token_jaccard_distinctive(
        "Please fetch the user records from the database",
        "I would like to fetch records",
    )
    assert abs(r - 0.4) < 1e-6


def test_jaccard_case_insensitive():
    assert abs(token_jaccard_distinctive("FETCH RECORDS", "fetch records") - 1.0) < 1e-9


def test_jaccard_deterministic():
    s = "the quick brown fox jumps over the lazy dog"
    t = "a brown fox jumped over the dog yesterday"
    assert token_jaccard_distinctive(s, t) == token_jaccard_distinctive(s, t)


# ── js_divergence (port of js_divergence.rs tests) ──

def test_js_identical_distributions_zero():
    # Same text → identical term distributions → 0 divergence (low penalty).
    assert abs(js_divergence("fetch records validate", "fetch records validate")) < 1e-9


def test_js_disjoint_distributions_one():
    # Single distinctive term each, fully disjoint → JS = 1 (base-2, high penalty).
    assert abs(js_divergence("apple", "zebra") - 1.0) < 1e-9


def test_js_empty_yields_zero():
    assert js_divergence("", "anything distinctive") == 0.0
    assert js_divergence("the and of", "is a was") == 0.0  # all stopwords → empty dists


def test_js_partial_overlap_between_zero_and_one():
    r = js_divergence("alpha beta gamma", "alpha delta epsilon")
    assert 0.0 < r < 1.0


def test_js_deterministic():
    a, b = "alpha beta gamma delta", "alpha beta epsilon zeta"
    assert js_divergence(a, b) == js_divergence(a, b)


# ── extracted_claims (port of claims.rs tests) ──

def _kinds(atoms: list[ExtractedAtom]) -> list[str]:
    return [a.kind for a in atoms]


def test_extract_iso_date():
    atoms = [a for a in extracted_claims("The launch is scheduled for 2026-05-16.") if a.kind == "date"]
    assert len(atoms) == 1 and atoms[0].literal == "2026-05-16" and atoms[0].is_specific_fact


def test_extract_numeric_with_unit():
    atoms = [a for a in extracted_claims("Response latency was 23 ms and disk used 512 MB.") if a.kind == "number"]
    assert len(atoms) == 2


def test_extract_currency():
    atoms = [a for a in extracted_claims("Cost: $19.99 per month.") if a.kind == "currency"]
    assert any("19.99" in a.literal for a in atoms)


def test_extract_currency_with_thousands():
    atoms = [a for a in extracted_claims("Capped at $1,000,000 total.") if a.kind == "currency"]
    assert atoms and atoms[0].literal == "$1,000,000"


def test_extract_named_entity():
    atoms = [a for a in extracted_claims("CEO is Tim Cook and Apple is based in Cupertino.") if a.kind == "entity"]
    assert any(a.literal == "Tim Cook" for a in atoms)


def test_extract_url():
    atoms = [a for a in extracted_claims("See https://example.com/docs for details.") if a.kind == "url"]
    assert len(atoms) == 1 and atoms[0].literal.startswith("https://example.com")


def test_extract_file_path():
    atoms = [a for a in extracted_claims("Edit /etc/hosts to add the entry.") if a.kind == "path"]
    assert atoms and atoms[0].literal == "/etc/hosts"


def test_extract_no_claims_in_generic_text():
    assert extracted_claims("Things are going well today.") == []


def test_extract_deterministic():
    s = "On 2026-05-16, Apple Computer announced 23 GB of storage at $99."
    assert extracted_claims(s) == extracted_claims(s)


def test_atom_summary_truncates():
    long = ExtractedAtom("entity", "x" * 100)
    assert long.summary.endswith("…") and long.summary.startswith("entity: ")


# ── luhn_valid (port of luhn.rs tests) ──

def test_luhn_rejects_random_16_digits():
    assert luhn_valid("1234567890123456") is False


def test_luhn_accepts_visa_test_number():
    assert luhn_valid("4111111111111111") is True


def test_luhn_accepts_mastercard_test_number():
    assert luhn_valid("5555555555554444") is True


def test_luhn_handles_separators():
    assert luhn_valid("4111 1111 1111 1111") is True
    assert luhn_valid("4111-1111-1111-1111") is True


def test_luhn_rejects_too_short_or_long():
    assert luhn_valid("123456789012") is False        # 12 digits
    assert luhn_valid("4" * 20) is False               # 20 digits
    assert luhn_valid("") is False
    assert luhn_valid("not a number at all") is False


def test_luhn_deterministic():
    assert luhn_valid("4111111111111111") == luhn_valid("4111111111111111")


# ── violates_declared_constraints (port of constraints.rs tests) ──

def test_constraints_no_declaration_no_violation():
    assert violates_declared_constraints("anything at all goes here", "summarize the contract") == []


def test_constraints_word_limit_violated():
    out = "this is a much much longer answer that exceeds five words"
    assert violates_declared_constraints(out, "Answer in 5 words or less.")


def test_constraints_word_limit_respected():
    assert violates_declared_constraints("this is a short answer", "Answer in 10 words or less.") == []


def test_constraints_char_limit_violated():
    assert violates_declared_constraints("x" * 50, "Reply in no more than 10 characters.")


def test_constraints_json_format_violated():
    assert violates_declared_constraints("not actually json", "Reply as JSON.")


def test_constraints_json_format_respected():
    assert violates_declared_constraints('{"key": "value"}', "Reply as JSON.") == []


def test_constraints_deterministic():
    a = violates_declared_constraints("one two three four", "Reply in 3 words.")
    b = violates_declared_constraints("one two three four", "Reply in 3 words.")
    assert a == b and a  # violated, both runs


# ── verifier integration: the short-circuit + the untouched genuine claim ──

_DOC = (
    "7.1 Vendor's aggregate liability under this Agreement shall not exceed the total "
    "fees paid by Customer in the twelve (12) months preceding the claim."
)
_GENUINE_CLAIM = "Liability is capped at the fees paid in the prior 12 months."
_FAB_CLAIM = "Liability is capped at $1,000,000 regardless of fees."


def _reply(*objs: dict) -> str:
    return json.dumps(list(objs))


def test_gate_short_circuits_fabricated_evidence_quote():
    """Gate ON: a 'confirmed' verdict whose cited quote is NOT in the document is
    flipped to unsupported (the killer check) — no second model call needed."""
    # The model confidently confirms, but cites a span absent from the document.
    reply = _reply(
        {
            "verdict": "confirmed",
            "confidence": 0.95,
            "reason": "model says it matches",
            "evidence_quote": "Vendor's liability is capped at one million dollars",
        }
    )
    vs = asyncio.run(
        Verifier(MockBackend(reply=reply), deterministic_gate=True).verify(_DOC, [_FAB_CLAIM])
    )
    assert vs[0].verdict is Verdict.UNSUPPORTED          # short-circuited to withhold
    assert vs[0].confidence == 0.0
    assert vs[0].deterministic_short_circuit is True     # auditable: the gate fired
    assert vs[0].evidence_quote is None
    # the cited span is overwhelmingly absent from the document (below the fab floor)
    assert vs[0].deterministic_overlap is not None and vs[0].deterministic_overlap < 0.25


def test_gate_leaves_genuine_quote_untouched():
    """Gate ON: a 'confirmed' verdict whose cited quote IS verbatim in the document is
    NOT touched (no false withhold) — confidence preserved, signals surfaced."""
    quote = "fees paid by Customer in the twelve (12) months preceding the claim"
    reply = _reply(
        {
            "verdict": "confirmed",
            "confidence": 0.9,
            "reason": "matches 7.1",
            "evidence_quote": quote,
        }
    )
    vs = asyncio.run(
        Verifier(MockBackend(reply=reply), deterministic_gate=True).verify(_DOC, [_GENUINE_CLAIM])
    )
    assert vs[0].verdict is Verdict.CONFIRMED            # genuine claim survives
    assert vs[0].confidence == 0.9                       # confidence untouched
    assert vs[0].deterministic_short_circuit is False
    assert abs(vs[0].deterministic_overlap - 1.0) < 1e-9  # quote fully present


def test_gate_off_is_byte_identical_but_annotated():
    """Gate OFF (default): the verdict is NOT changed (no short-circuit, no penalty),
    but the read-only deterministic signals are still surfaced for audit."""
    reply = _reply(
        {
            "verdict": "confirmed",
            "confidence": 0.95,
            "reason": "fabricated span the model still confirmed",
            "evidence_quote": "Vendor's liability is capped at one million dollars",
        }
    )
    vs = asyncio.run(Verifier(MockBackend(reply=reply)).verify(_DOC, [_FAB_CLAIM]))
    assert vs[0].verdict is Verdict.CONFIRMED            # gate OFF → unchanged verdict
    assert vs[0].confidence == 0.95
    assert vs[0].deterministic_short_circuit is False
    assert vs[0].deterministic_overlap is not None        # still annotated for audit
    assert vs[0].atoms_graded is not None


def test_gate_lowers_confidence_for_weak_overlap():
    """Gate ON: a partially-present quote (0 < overlap < ceiling) gets its confidence
    scaled DOWN by the overlap fraction — only ever lowered, never raised."""
    # Quote shares a distinctive opening with the document but tails off into invented
    # text, so some windows match and some do not → overlap strictly between 0 and 0.5.
    quote = "Vendor's aggregate liability under this xqzv nonsense tail that is absent"
    reply = _reply(
        {"verdict": "confirmed", "confidence": 0.8, "reason": "partial span", "evidence_quote": quote}
    )
    vs = asyncio.run(
        Verifier(MockBackend(reply=reply), deterministic_gate=True).verify(_DOC, [_GENUINE_CLAIM])
    )
    o = vs[0].deterministic_overlap
    assert o is not None and 0.25 <= o < 0.6            # lands in the weak-overlap band
    assert vs[0].verdict is Verdict.CONFIRMED           # not short-circuited
    assert vs[0].confidence < 0.8                       # penalized, never raised
    assert abs(vs[0].confidence - 0.8 * o) < 1e-12      # scaled by the overlap fraction


def test_gate_never_upgrades_unsupported():
    """Gate ON: an UNSUPPORTED verdict (no quote) is never up-graded — fail-safe held."""
    reply = _reply({"verdict": "unsupported", "confidence": 0.9, "reason": "absent", "evidence_quote": None})
    vs = asyncio.run(
        Verifier(MockBackend(reply=reply), deterministic_gate=True).verify(_DOC, [_FAB_CLAIM])
    )
    assert vs[0].verdict is Verdict.UNSUPPORTED
    assert vs[0].atoms_graded is not None                # annotated even with no quote


# ── normalize (formatting-insensitive canonicalization) ──

def test_normalize_collapses_whitespace_and_lowercases():
    assert normalize("Hello   World\n\tAgain") == "hello world again"


def test_normalize_folds_smart_quotes_and_dashes():
    assert normalize("“fees paid” — prior 12’s") == '"fees paid" - prior 12\'s'


def test_normalize_empty_is_empty():
    assert normalize("") == ""
    assert normalize("   \n\t  ") == ""


def test_normalize_idempotent():
    s = "“The  Quick—Brown”  Fox"
    assert normalize(normalize(s)) == normalize(s)


def test_verbatim_overlap_dominates_raw_on_formatting_diffs():
    doc = "fees paid by Customer in the twelve (12) months preceding the claim"
    # a genuine quote that differs ONLY in formatting (smart quotes, doubled space, NL)
    quote = "fees   paid by Customer in the twelve (12)\nmonths preceding the claim"
    # raw ratio is dinged by the formatting; verbatim ratio recovers full presence
    assert verbatim_overlap_ratio(quote, doc) == 1.0
    assert verbatim_overlap_ratio(quote, doc) >= substring_overlap_ratio(quote, doc)


def test_verbatim_overlap_absent_quote_is_zero():
    doc = "Vendor's liability is capped at the prior twelve months' fees."
    assert verbatim_overlap_ratio("capped at one million dollars total", doc) < 0.25


# ── claim_survives_ablation (the ablation test) ──

_ABL_DOC = (
    "Confidential Information is protected for 3 years after disclosure. "
    "Vendor shall notify Client of any security breach within 72 hours. "
    "Confidential Information is protected for 3 years after disclosure in Schedule B too."
)


def test_ablation_survives_when_supported_elsewhere():
    # the claim text appears verbatim TWICE; ablating one occurrence leaves the other.
    claim = "Confidential Information is protected for 3 years after disclosure"
    quote = "Confidential Information is protected for 3 years after disclosure"
    assert claim_survives_ablation(claim, quote, _ABL_DOC) is True


def test_ablation_fails_when_single_sourced():
    # the only support for this claim is the one cited span; ablate it → unsupported.
    doc = "Vendor shall notify Client of any security breach within 72 hours."
    claim = "Vendor shall notify Client of any security breach within 72 hours."
    quote = "Vendor shall notify Client of any security breach within 72 hours"
    assert claim_survives_ablation(claim, quote, doc) is False


def test_ablation_absent_quote_does_not_withhold():
    # quote NOT present → there is nothing to ablate; the ablation test must NOT report
    # "does not survive" (that would be the gate withholding — forbidden). Returns True;
    # the absent-quote case is the routing layer's job (it escalates, never withholds).
    doc = "Vendor's liability is capped at the prior twelve months' fees."
    assert claim_survives_ablation("anything", "totally absent span here", doc) is True


def test_ablation_degenerate_inputs_never_withhold():
    assert claim_survives_ablation("", "q", "doc") is True
    assert claim_survives_ablation("c", "", "doc") is True
    assert claim_survives_ablation("c", "q", "") is True


# ── route_claim (the routing table) ──

def test_route_supported_present_and_survives():
    claim = "Confidential Information is protected for 3 years after disclosure"
    quote = "Confidential Information is protected for 3 years after disclosure"
    sig = route_claim(claim, quote, _ABL_DOC)
    assert sig.route is GateRoute.SUPPORTED
    assert sig.ablation_survived is True
    assert sig.verbatim_overlap == 1.0


def test_route_judge_present_but_single_sourced():
    doc = "Vendor shall notify Client of any security breach within 72 hours."
    claim = "Vendor shall notify Client of any security breach within 72 hours."
    quote = "Vendor shall notify Client of any security breach within 72 hours"
    sig = route_claim(claim, quote, doc)
    assert sig.route is GateRoute.JUDGE          # flagged, not withheld
    assert sig.ablation_survived is False


def test_route_escalate_absent_quote():
    doc = "Vendor's liability is capped at the prior twelve months' fees."
    sig = route_claim("Liability is one million", "capped at one million dollars total", doc)
    assert sig.route is GateRoute.ESCALATE
    assert sig.verbatim_overlap < 0.95


def test_route_escalate_missing_quote():
    sig = route_claim("some claim", None, "some document text here at length")
    assert sig.route is GateRoute.ESCALATE


def test_route_flags_normalization_when_load_bearing():
    doc = "fees paid by Customer in the twelve (12) months preceding the claim"
    quote = "fees   paid by Customer\nin the twelve (12) months preceding the claim"
    sig = route_claim("fees paid by Customer in the twelve (12) months preceding the claim", quote, doc)
    assert sig.verbatim_overlap == 1.0
    assert sig.normalized is True                # raw overlap fell short, normalize saved it


# ── ablation gate via the Verifier (routing, penalize/escalate, NEVER auto-withhold) ──

_GATE_DOC = (
    "7.1 Vendor's aggregate liability under this Agreement shall not exceed the total "
    "fees paid by Customer in the twelve (12) months preceding the claim."
)


def test_ablation_gate_genuine_present_quote_not_withheld():
    """Gate ON: a confirmed verdict citing a VERBATIM-present quote is never penalized
    into a withhold — verdict + confidence preserved, route annotated."""
    quote = "fees paid by Customer in the twelve (12) months preceding the claim"
    reply = _reply({"verdict": "confirmed", "confidence": 0.9, "reason": "matches", "evidence_quote": quote})
    vs = asyncio.run(
        Verifier(MockBackend(reply=reply), ablation_gate=True).verify(_GATE_DOC, [_GENUINE_CLAIM])
    )
    v = vs[0]
    assert v.verdict is Verdict.CONFIRMED
    assert v.confidence == 0.9                    # NOT penalized
    assert v.needs_human() is False               # NOT escalated → no false withhold
    assert v.force_needs_human is False
    assert v.deterministic_route in ("supported", "judge")  # present → never "escalate"
    assert v.deterministic_verbatim_overlap == 1.0


def test_ablation_gate_genuine_with_formatting_diffs_not_withheld():
    """Gate ON: a genuine quote that differs only in formatting still clears the
    verbatim-present floor (via normalize) → not escalated."""
    quote = "fees   paid by Customer in the twelve (12)\nmonths preceding the claim"
    reply = _reply({"verdict": "confirmed", "confidence": 0.88, "reason": "matches", "evidence_quote": quote})
    vs = asyncio.run(
        Verifier(MockBackend(reply=reply), ablation_gate=True).verify(_GATE_DOC, [_GENUINE_CLAIM])
    )
    v = vs[0]
    assert v.confidence == 0.88
    assert v.needs_human() is False
    assert v.deterministic_route != "escalate"
    assert v.deterministic_normalized is True


def test_ablation_gate_absent_quote_escalates_but_does_not_auto_withhold():
    """Gate ON: a confirmed verdict citing an ABSENT quote is penalized + escalated, but
    the VERDICT is NOT flipped to unsupported and confidence is NOT zeroed — the judge
    and threshold remain the arbiter (no deterministic auto-withhold)."""
    reply = _reply({
        "verdict": "confirmed",
        "confidence": 0.95,
        "reason": "model confirmed a span absent from the doc",
        "evidence_quote": "Vendor's liability is capped at one million dollars",
    })
    vs = asyncio.run(
        Verifier(MockBackend(reply=reply), ablation_gate=True).verify(_GATE_DOC, [_FAB_CLAIM])
    )
    v = vs[0]
    assert v.verdict is Verdict.CONFIRMED         # NOT auto-flipped (no auto-withhold)
    assert v.confidence < 0.95                    # penalized (only lowered)
    assert v.confidence > 0.0                     # NOT zeroed by the gate
    assert v.force_needs_human is True            # escalated to a human
    assert v.needs_human() is True
    assert v.deterministic_route == "escalate"
    assert v.escalate_reason is not None


def test_ablation_gate_never_relaxes_a_model_withhold():
    """Gate ON: an UNSUPPORTED verdict is annotated but never up-graded / un-escalated."""
    reply = _reply({"verdict": "unsupported", "confidence": 0.9, "reason": "absent", "evidence_quote": None})
    vs = asyncio.run(
        Verifier(MockBackend(reply=reply), ablation_gate=True).verify(_GATE_DOC, [_FAB_CLAIM])
    )
    assert vs[0].verdict is Verdict.UNSUPPORTED
    assert vs[0].deterministic_route is not None  # annotated


def test_ablation_gate_off_is_byte_identical():
    """Gate OFF (default): NO ablation fields populated, verdict untouched."""
    quote = "fees paid by Customer in the twelve (12) months preceding the claim"
    reply = _reply({"verdict": "confirmed", "confidence": 0.9, "reason": "matches", "evidence_quote": quote})
    vs = asyncio.run(Verifier(MockBackend(reply=reply)).verify(_GATE_DOC, [_GENUINE_CLAIM]))
    v = vs[0]
    assert v.verdict is Verdict.CONFIRMED and v.confidence == 0.9
    assert v.deterministic_route is None          # gate OFF → not run
    assert v.deterministic_ablation_survived is None
    assert v.force_needs_human is False


# ── OFFLINE VALIDATION: false-withhold == 0 on the genuine set ──

def test_offline_false_withhold_is_zero_on_genuine_and_flags_fabrications():
    """The whole point. Over the gold calibration cases (and the seeded-liar fixture),
    drive the ablation gate with a backend that behaves like the verbatim-quote prompt
    demands: for a GENUINE claim it cites a REAL substring of the document; for a
    FABRICATION it cites a span absent from the document. Assert:
      (i)  ZERO genuine claims are escalated/penalized into a withhold by the gate, and
      (ii) EVERY fabrication (absent quote) is flagged/escalated.
    """
    import json as _json

    calib = _json.load(open(_CALIB))["cases"]

    # genuine = gold in {confirmed, partial}; fabricated = gold unsupported.
    def _longest_real_span(doc: str) -> str:
        # a verbatim span the "model" can honestly cite for a genuine claim: a 60-char
        # window of the actual document (mimics the verbatim-quote prompt).
        d = doc.strip()
        return d[: min(len(d), 64)]

    genuine = [c for c in calib if c["gold"] in ("confirmed", "partial")]
    fabricated = [c for c in calib if c["gold"] == "unsupported"]

    false_withholds = 0
    for c in genuine:
        quote = _longest_real_span(c["contract"])     # an honest verbatim citation
        reply = _reply({"verdict": "confirmed", "confidence": 0.9, "reason": "ok", "evidence_quote": quote})
        vs = asyncio.run(
            Verifier(MockBackend(reply=reply), ablation_gate=True).verify(c["contract"], [c["claim"]])
        )
        v = vs[0]
        # the gate must NOT have escalated/penalized a genuine, present-quote claim
        if v.force_needs_human or v.deterministic_route == "escalate" or v.confidence < 0.9:
            false_withholds += 1
        assert v.deterministic_route != "escalate", f"genuine case {c['id']} wrongly escalated"

    assert false_withholds == 0, f"FALSE-WITHHOLD on genuine set: {false_withholds}"

    flagged = 0
    for c in fabricated:
        # a fabrication cites an absent span (not in the contract).
        fab_quote = "Vendor shall indemnify Client up to $1,000,000 for any third-party claim"
        assert verbatim_overlap_ratio(fab_quote, c["contract"]) < 0.95  # truly absent
        reply = _reply({"verdict": "confirmed", "confidence": 0.95, "reason": "x", "evidence_quote": fab_quote})
        vs = asyncio.run(
            Verifier(MockBackend(reply=reply), ablation_gate=True).verify(c["contract"], [c["claim"]])
        )
        v = vs[0]
        if v.deterministic_route == "escalate" and v.force_needs_human and v.confidence < 0.95:
            flagged += 1
        # gate must NOT have auto-withheld (verdict still the model's, confidence > 0)
        assert v.verdict is Verdict.CONFIRMED and v.confidence > 0.0

    assert flagged == len(fabricated), f"only {flagged}/{len(fabricated)} fabrications flagged"
    print(f"    offline: false_withhold=0 on {len(genuine)} genuine; "
          f"{flagged}/{len(fabricated)} fabrications flagged")


def test_offline_false_withhold_zero_on_seeded_liar_fixture():
    """Same invariant over the LOCKED seeded-liar fixture's GENUINE claims. Per the
    verbatim-quote prompt the model cites a span FROM THE DOCUMENT (not the claim — a
    genuine claim may be a paraphrase). A genuine claim is grounded, so an honest model
    can always cite a real document span; the gate must never escalate/penalize that
    into a withhold. We simulate the honest citation with a real 64-char document
    window and assert false-withhold == 0."""
    import json as _json

    fx = _json.load(open(_FIXTURE))
    genuine = [c for c in fx if c["label"] == "genuine"]
    assert genuine  # sanity

    false_withholds = 0
    for c in genuine:
        doc = c["contract"].strip()
        quote = doc[: min(len(doc), 64)]          # an HONEST verbatim citation from the doc
        assert verbatim_overlap_ratio(quote, doc) >= 0.95
        reply = _reply({"verdict": "confirmed", "confidence": 0.9, "reason": "ok", "evidence_quote": quote})
        vs = asyncio.run(
            Verifier(MockBackend(reply=reply), ablation_gate=True).verify(c["contract"], [c["claim"]])
        )
        v = vs[0]
        if v.force_needs_human or v.deterministic_route == "escalate" or v.confidence < 0.9:
            false_withholds += 1
    assert false_withholds == 0, f"FALSE-WITHHOLD on seeded-liar genuine set: {false_withholds}"
    print(f"    offline (fixture): false_withhold=0 on {len(genuine)} genuine claims")


def _run_all():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"  ✓ {fn.__name__}")
    print(f"\n{len(fns)} passed")


if __name__ == "__main__":
    _run_all()
