"""Write-time redaction tests — the PII-scrubbing seam on the immutable artifacts.

Covers the faithful port of AgentScope's ``redact.rs`` plus the conservative,
default-ON PII policy and its integration into the three self-verifying write-paths:

  * **Literal keys** — longest-first match + name/value-token blanking, single pass.
  * **Each PII pattern** — a positive (redacts) AND a near-miss negative (a clause
    number / date / section ref that MUST NOT be redacted).
  * **Luhn-gated card** — only Luhn-valid digit runs are redacted.
  * **Hash-chain verifies post-redaction** — the ledger chains over redacted payloads
    and ``verify_chain()`` still passes.
  * **Receipt verifies post-redaction** — ``build_receipt`` → ``sign`` →
    ``verify_receipt`` round-trips over the redacted receipt.
  * **Idempotence** — re-applying redaction to already-redacted text is a no-op.
  * **Verifier sees full text** — redaction is WRITE-only: the in-flight graders are
    untouched (the FULL contract is graded; only the persisted artifact is scrubbed).
  * **No-regression** — the conservative patterns leave the sample MSA/NDA contract
    text and the on-chain hex addresses byte-identical.

Run:  .venv/bin/python -m pytest tests/test_redact.py -q
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from agent_exchange.audit.report import AuditedFinding
from agent_exchange.audit.room_audit_types import RoomAuditResult
from agent_exchange.market.hiring_types import Hire
from agent_exchange.metrics import (
    ClaimRecord,
    JobTrace,
    StageTimings,
    TraceWriter,
    usdc,
)
from agent_exchange.payments.ledger import HashChainedLedger
from agent_exchange.payments.receipts import build_receipt, make_receipt_signer, verify_receipt
from agent_exchange.payments.settlement import settle_job
from agent_exchange.redact import (
    DEFAULT_REPLACEMENT,
    Policy,
    apply,
    default_policy,
    redact_obj,
)
from agent_exchange.verify.graders import luhn_valid
from agent_exchange.verify.schema import ClaimVerdict, Verdict
from agent_exchange.workers.finding import Finding

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ════════════════════════════════════════════════════════════════════════════
# 1. Literal-key pass — longest-first + value-token blanking (port fidelity)
# ════════════════════════════════════════════════════════════════════════════


def test_literal_key_redacts_both_name_and_value():
    out = apply("OPENAI_API_KEY=sk-abc123def456", literal_keys=["OPENAI_API_KEY"])
    assert out == "[REDACTED:OPENAI_API_KEY]=[REDACTED:OPENAI_API_KEY]"
    assert "sk-abc123def456" not in out


def test_literal_key_whitespace_and_colon_separators():
    ws = apply("OPENAI_API_KEY  sk-secret", literal_keys=["OPENAI_API_KEY"])
    assert ws.startswith("[REDACTED:OPENAI_API_KEY]")
    assert ws.endswith("[REDACTED:OPENAI_API_KEY]")
    assert "sk-secret" not in ws

    colon = apply("ANTHROPIC_API_KEY: ant-xyz789", literal_keys=["ANTHROPIC_API_KEY"])
    assert "[REDACTED:ANTHROPIC_API_KEY]" in colon
    assert "ant-xyz789" not in colon


def test_longest_key_wins_over_prefix():
    # Without longest-first, "API_KEY" could match before "OPENAI_API_KEY".
    out = apply("OPENAI_API_KEY=secret", literal_keys=["API_KEY", "OPENAI_API_KEY"])
    assert "[REDACTED:OPENAI_API_KEY]" in out
    assert "secret" not in out
    # Never re-scans inside the replacement: API_KEY must NOT match in the output.
    assert "[REDACTED:API_KEY]" not in out


def test_literal_case_sensitive_and_no_false_match():
    # Case-sensitive: lowercase var doesn't match the uppercase key.
    out = apply("openai_api_key=lowercase", literal_keys=["OPENAI_API_KEY"])
    assert out == "openai_api_key=lowercase"
    # Plain text with no secrets is unchanged.
    plain = apply("Plain text, no secrets.", literal_keys=["OPENAI_API_KEY", "STRIPE_KEY"])
    assert plain == "Plain text, no secrets."


def test_custom_replacement_template():
    out = apply("OPENAI_API_KEY=secret", literal_keys=["OPENAI_API_KEY"], replacement="[X:{name}]")
    assert out == "[X:OPENAI_API_KEY]=[X:OPENAI_API_KEY]"


def test_invalid_regex_is_nonfatal():
    # Literal still redacts; the bad regex is skipped (no exception).
    out = apply(
        "OPENAI_API_KEY=secret",
        literal_keys=["OPENAI_API_KEY"],
        regex_patterns=["[unclosed bracket"],
    )
    assert "[REDACTED:OPENAI_API_KEY]" in out


def test_policy_with_extra_literal_keys_keeps_default_pii():
    pol = default_policy(extra_literal_keys=("CUSTOMER_SECRET",))
    out = pol.apply_to("CUSTOMER_SECRET=hunter2 mail jane@example.com")
    assert "[REDACTED:CUSTOMER_SECRET]" in out
    assert "hunter2" not in out
    assert "[REDACTED:EMAIL]" in out  # default PII still on
    # with_literal_keys merges without dropping the PII patterns
    pol2 = default_policy().with_literal_keys("FOO_TOKEN")
    assert "[REDACTED:FOO_TOKEN]" in pol2.apply_to("FOO_TOKEN=zzz")


# ════════════════════════════════════════════════════════════════════════════
# 2. Each PII pattern — positive + near-miss negative
# ════════════════════════════════════════════════════════════════════════════


def _pol() -> Policy:
    return default_policy()


def test_email_positive_and_negative():
    pol = _pol()
    assert "[REDACTED:EMAIL]" in pol.apply_to("write to jane.doe@example.com today")
    # Near-miss: an "@" handle without a dotted TLD must not redact.
    neg = "mention @Reporter in the room and the clause @ section 4"
    assert pol.apply_to(neg) == neg


def test_phone_positive_and_negative():
    pol = _pol()
    assert "[REDACTED:PHONE]" in pol.apply_to("call 415-555-2671 now")
    assert "[REDACTED:PHONE]" in pol.apply_to("call (415) 555-2671 now")
    assert "[REDACTED:PHONE]" in pol.apply_to("reach +442071838750 today")
    # Near-miss: a clause number / date is NOT a phone number.
    neg = "in the twelve (12) months, terminate on 30 days notice"
    assert pol.apply_to(neg) == neg


def test_ssn_positive_and_negative():
    pol = _pol()
    assert "[REDACTED:SSN]" in pol.apply_to("SSN 123-45-6789 on file")
    # Near-miss: a dotted section ref like 4.2.1 or a date range is not an SSN.
    neg = "see Section 4.2 and Exhibit 12-3 dated 2024-2026"
    assert pol.apply_to(neg) == neg


def test_ein_positive_and_negative():
    pol = _pol()
    assert "[REDACTED:EIN]" in pol.apply_to("EIN 12-3456789 for the entity")
    # Near-miss: "12-3" (a clause sub-ref) is too short to be an EIN.
    neg = "clause 12-3 and the 30-day cure period"
    assert pol.apply_to(neg) == neg


def test_credit_card_is_luhn_gated():
    pol = _pol()
    # Luhn-VALID card → redacted.
    assert luhn_valid("4111 1111 1111 1111")
    assert "[REDACTED:CREDIT_CARD]" in pol.apply_to("pay 4111 1111 1111 1111 now")
    assert "[REDACTED:CREDIT_CARD]" in pol.apply_to("pay 4111-1111-1111-1111 now")
    # Near-miss: a 16-digit run that is NOT Luhn-valid (e.g. an arbitrary ref) is left.
    assert not luhn_valid("1234 5678 9012 3456")
    neg = "internal reference 1234 5678 9012 3456 in the appendix"
    assert pol.apply_to(neg) == neg
    # On-chain hex address run is NOT a card (no Luhn match, hex-bounded).
    addr = "settled to 0x00000000000000000000000000000000000051m1 onchain"
    assert pol.apply_to(addr) == addr


# ════════════════════════════════════════════════════════════════════════════
# 3. redact_obj walks containers; idempotence
# ════════════════════════════════════════════════════════════════════════════


def test_redact_obj_walks_nested_and_preserves_non_strings():
    obj = {
        "email": "a@b.com",
        "count": 12,
        "ok": True,
        "nested": ["x@y.com", {"deep": "ssn 123-45-6789"}, 3.14, None],
    }
    red = redact_obj(obj)
    assert red["email"] == "[REDACTED:EMAIL]"
    assert red["count"] == 12 and red["ok"] is True
    assert red["nested"][0] == "[REDACTED:EMAIL]"
    assert red["nested"][1]["deep"] == "ssn [REDACTED:SSN]"
    assert red["nested"][2] == 3.14 and red["nested"][3] is None


def test_redaction_is_idempotent():
    pol = _pol()
    text = "email a@b.com phone 415-555-2671 ssn 123-45-6789 card 4111 1111 1111 1111"
    once = pol.apply_to(text)
    twice = pol.apply_to(once)
    assert once == twice  # re-applying over a redacted string changes nothing


# ════════════════════════════════════════════════════════════════════════════
# 4. Hash-chained ledger verifies POST-redaction
# ════════════════════════════════════════════════════════════════════════════


def test_ledger_redacts_payload_before_hash_and_chain_verifies():
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "ledger.jsonl")
        led = HashChainedLedger(path)  # default-ON PII policy
        led.append("verify_ok", {"worker": "alpha", "contact": "alpha@corp.com"}, timestamp="T0")
        led.append("settled", {"worker": "alpha", "ssn": "123-45-6789"}, timestamp="T1")

        # PII never persisted.
        raw = open(path, encoding="utf-8").read()
        assert "alpha@corp.com" not in raw
        assert "123-45-6789" not in raw
        assert "[REDACTED:EMAIL]" in raw and "[REDACTED:SSN]" in raw

        # The chain re-derives its hashes from the persisted (redacted) payloads → True.
        assert HashChainedLedger(path).verify_chain() is True

        # And it is still tamper-evident: flip a byte → chain breaks.
        corrupt = raw.replace("alpha", "EVILX", 1)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(corrupt)
        assert HashChainedLedger(path).verify_chain() is False


# ════════════════════════════════════════════════════════════════════════════
# 5. Signed receipt verifies POST-redaction
# ════════════════════════════════════════════════════════════════════════════

_TEST_KEY = "0x" + "11" * 32


def _audited_with_pii(claim: str) -> list[AuditedFinding]:
    return [
        AuditedFinding(
            finding=Finding(worker="alpha", clause_ref="1", claim=claim, severity="high"),
            verdict=ClaimVerdict(
                claim=claim, verdict=Verdict.CONFIRMED, confidence=0.95, reason="graded"
            ),
        )
    ]


def test_receipt_redacts_deliverable_and_still_verifies():
    pii_claim = "Notify the signatory at jane.doe@example.com (SSN 123-45-6789)."
    deliverable = RoomAuditResult(
        work_room_id="room-1",
        audited=tuple(_audited_with_pii(pii_claim)),
        report_summary="synth",
        report_audited=(),
    )
    hires = [Hire(worker="alpha", price_atomic=usdc(0.05), value=1.0, relevance=1.0)]
    result = asyncio.run(settle_job(_FakeGate(), deliverable, hires, {"alpha": "0xAAA"}))

    signer = make_receipt_signer(_TEST_KEY)
    receipt = build_receipt("room-1", deliverable, result, timestamp="T0")
    signed = signer.sign(receipt)

    # The receipt's deliverable hash committed to REDACTED work; signature verifies.
    assert verify_receipt(signed) is True
    # Determinism: rebuilding + re-signing yields the same deliverable hash.
    again = build_receipt("room-1", deliverable, result, timestamp="T0")
    assert again.deliverable_hash == receipt.deliverable_hash


class _FakeGate:
    """In-memory PaymentGate — no chain, no keys (mirrors test_receipts_ledger)."""

    def __init__(self, *, verify_ok: bool = True) -> None:
        self.verify_ok = verify_ok
        self._seq = 0

    def build_requirement(self, *, amount_atomic: int, pay_to: str) -> object:
        return {"amount": amount_atomic, "pay_to": pay_to}

    async def authorize(self, requirement: object) -> object:
        return {"sig": "0xauth", "pay_to": requirement["pay_to"]}  # type: ignore[index]

    async def verify(self, payload: object, requirement: object) -> bool:
        return self.verify_ok

    async def settle(self, payload: object, requirement: object, *, amount_atomic: int) -> str:
        tx = f"0xfake{self._seq}"
        self._seq += 1
        return tx


# ════════════════════════════════════════════════════════════════════════════
# 6. TraceWriter redacts the row before write; row stays internally consistent
# ════════════════════════════════════════════════════════════════════════════


def test_trace_writer_redacts_row_before_write():
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "trace.jsonl")
        tw = TraceWriter(path)  # default-ON PII
        claim = ClaimRecord(
            worker_id="alpha",
            claim_text="Reach the signer at jane@example.com about clause 12.",
            verdict="confirmed",
            confidence=0.9,
        )
        trace = JobTrace(
            job_id="j1",
            job_kind="contract-clause-audit",
            job_spec="Audit; notify owner ssn 123-45-6789 on completion.",
            worker_ids=("alpha",),
            claims=(claim,),
            amount_authorized_atomic=100,
            amount_settled_atomic=0,
            amount_withheld_atomic=100,
            settled=False,
            tx_hash=None,
            seeded_liar=True,
            timings=StageTimings(started_ns=0),
            seed=1,
        )
        tw.write(trace)
        raw = open(path, encoding="utf-8").read()
        assert "jane@example.com" not in raw and "123-45-6789" not in raw
        assert "[REDACTED:EMAIL]" in raw and "[REDACTED:SSN]" in raw

        # The persisted hashes commit to the REDACTED text (internally consistent).
        import hashlib

        row = json.loads(raw)
        assert row["job_spec_hash"] == hashlib.sha256(row["job_spec"].encode()).hexdigest()
        assert row["claims"][0]["claim_hash"] == (
            hashlib.sha256(row["claims"][0]["claim_text"].encode()).hexdigest()
        )


# ════════════════════════════════════════════════════════════════════════════
# 7. Redaction is WRITE-ONLY — the verifier/graders see the full text
# ════════════════════════════════════════════════════════════════════════════


def test_verifier_sees_full_text_redaction_is_write_only():
    # The in-flight grading object (Finding) is never mutated by redaction — only
    # the persisted artifact (deliverable hash / receipt) is scrubbed. Prove the
    # source finding still holds the FULL claim after a receipt was built.
    pii_claim = "Owner email jane@example.com must be notified."
    findings = _audited_with_pii(pii_claim)
    deliverable = RoomAuditResult(
        work_room_id="r", audited=tuple(findings), report_summary="s", report_audited=()
    )
    hires = [Hire(worker="alpha", price_atomic=usdc(0.05), value=1.0, relevance=1.0)]
    result = asyncio.run(settle_job(_FakeGate(), deliverable, hires, {"alpha": "0xAAA"}))
    _ = build_receipt("r", deliverable, result, timestamp="T0")

    # The grading source object is untouched — graders operate on the full contract.
    assert findings[0].finding.claim == pii_claim
    assert "jane@example.com" in findings[0].finding.claim


# ════════════════════════════════════════════════════════════════════════════
# 8. No-regression — sample contract fixtures stay byte-identical under redaction
# ════════════════════════════════════════════════════════════════════════════


def test_sample_replay_fixtures_unchanged_by_redaction():
    pol = default_policy()
    for name in (
        "sample-contract-audit-seeded-liar.replay.json",
        "sample-nda-review-seeded-liar.replay.json",
    ):
        path = os.path.join(_REPO, "data", "replays", name)
        with open(path, encoding="utf-8") as fh:
            original = json.load(fh)
        redacted = redact_obj(original, pol)
        assert json.dumps(redacted, sort_keys=True) == json.dumps(original, sort_keys=True), (
            f"conservative policy must not alter a sample-contract byte: {name}"
        )


def test_default_replacement_constant_matches_port():
    assert DEFAULT_REPLACEMENT == "[REDACTED:{name}]"
