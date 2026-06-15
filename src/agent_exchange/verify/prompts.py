"""Verifier prompt (versioned). Strict, grounded claim-vs-contract checking.

The verifier's grounded claim-vs-contract prompt — the most important prompt in
the project. Design rules:
  - Judge ONLY against the supplied contract text (no outside legal knowledge).
  - A fabricated / absent clause is UNSUPPORTED, however plausible it sounds.
  - Honest, calibrated confidence (lower when the text is ambiguous).
  - Machine-parseable: a JSON array, one object per claim, IN ORDER, no prose.
"""

from __future__ import annotations

PROMPT_VERSION = "verifier_v1"


def verifier_system(document: str = "contract") -> str:
    """Build the verifier system prompt for a given document type.

    The document word is parameterized so the same strict claim-vs-document
    verifier can grade claims about any document type (a contract, an NDA, ...).
    The default ``"contract"`` reproduces the original prompt verbatim.

    Args:
        document: The document-type word (lowercase), e.g. ``"contract"`` or
            ``"nda"``. Used lowercase in prose and uppercased as the section label.

    Returns:
        The full system prompt string.
    """
    doc = document
    DOC = document.upper()
    return f"""You are a strict {doc}-claim verifier. You receive a {DOC} \
(the ONLY ground truth) and a numbered list of CLAIMS that an automated auditor made \
about it. For EACH claim decide whether the {DOC} TEXT supports it, using ONLY the \
{doc} text — never outside legal knowledge, never assumptions, never charity.

For each claim, produce an object with:
- "verdict": exactly one of
    "confirmed"   - the {doc} text clearly and specifically supports the claim,
    "partial"     - the text supports a weaker/narrower version, or only part of it,
    "unsupported" - the text does not support it, contradicts it, or the cited clause is absent.
- "confidence": a number in [0,1], your HONEST calibrated confidence in this verdict
  (use lower values when the text is ambiguous or you are unsure).
- "reason": one sentence explaining the verdict.
- "evidence_quote": a span COPIED VERBATIM, character-for-character, from the {doc} —
  the exact text that supports the claim (you may copy a longer run than the minimum).
  Use null ONLY when the verdict is "unsupported".

Hard rules:
- If the {doc} does not actually say it, the verdict is "unsupported" — even if the
  claim sounds legally reasonable. A fabricated clause MUST be caught.
- "evidence_quote" MUST be a substring that appears verbatim in the {doc}: copy it
  exactly, do NOT paraphrase, summarize, reword, or invent it. If you cannot find a
  verbatim supporting span in the {doc}, the verdict is "unsupported" and the quote is
  null. A quote you cannot copy from the {doc} is grounds to withhold, not to confirm.

Output ONLY a JSON array with one object per claim, in the SAME ORDER as the claims.
No surrounding prose, no markdown code fences."""


# Module-level default (document="contract") so existing importers keep working.
VERIFIER_SYSTEM = verifier_system()


def build_user_message(
    contract_text: str, claims: list[str], *, document: str = "contract"
) -> str:
    """The user turn: the document, then the numbered claims to verify.

    Args:
        contract_text: The document text (ground truth).
        claims: The claims to verify, in order.
        document: The document-type word for the section label (default
            ``"contract"`` → ``CONTRACT (ground truth):``).
    """
    DOC = document.upper()
    numbered = "\n".join(f"{i}. {c}" for i, c in enumerate(claims, 1))
    return (
        f"{DOC} (ground truth):\n"
        '"""\n'
        f"{contract_text.strip()}\n"
        '"""\n\n'
        f"CLAIMS to verify ({len(claims)}):\n"
        f"{numbered}\n\n"
        "Return the JSON array now — one object per claim, in order."
    )
