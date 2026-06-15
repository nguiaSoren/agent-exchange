"""The six clause-audit specialists + the pool factory — the worker side of the
Agent Exchange.

Each specialist is a single-clause-area auditor: it reads the WHOLE contract but
reports ONLY on its own clause type (liability, IP, termination, tax, data/privacy,
or indemnity). It emits a JSON array of **findings**, each one a discrete, checkable
assertion the downstream verifier can confirm against the contract text — that
verification is what makes the work payable, so vague or fabricated claims are
worthless by construction.

Public API:
  - `SpecialistWorker`     — a `Specialist`-protocol-satisfying worker (name/area/
    system_prompt/backend) whose `findings(contract)` runs one model call and parses
    the result into `list[Finding]`.
  - `SPECIALISTS`          — the registry of (name, area, system_prompt) triples (6).
  - `make_pool_specialists(provider, model)` — builds all six on one backend.

Design notes:
  - The model id is NEVER hardcoded — it always flows in from the caller via
    `make_pool_specialists(provider, model)`.
  - `temperature=0.0` for determinism/auditability; the prompts do all the steering.
  - Parsing is delegated to `parse_findings`, which is fail-soft: a worker that emits
    junk (or whose area is absent) yields `[]` — nothing to verify, nothing to pay.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..core.backend import ModelBackend, make_backend
from ..core.types import Message
from .finding import Finding, Specialist, parse_findings

# ---------------------------------------------------------------------------
# Worker
# ---------------------------------------------------------------------------


@dataclass
class SpecialistWorker:
    """A single clause-area audit specialist.

    Satisfies the `Specialist` protocol (`.name` + `async findings(contract)`), so a
    pool can fan out over a heterogeneous list of these. One worker == one clause area
    == one model call per contract.

    Attributes:
        name: Stable identifier for this specialist (e.g. ``"liability"``). This is
            stamped onto every `Finding.worker` it produces, so it MUST be unique
            within a pool for findings to be attributable (and payable) to the right
            worker.
        area: Short human-readable description of the clause area audited.
        system_prompt: The engineered instruction that scopes the model to this area
            and pins the exact JSON output contract.
        backend: The `ModelBackend` used to run the audit. Injected (never constructed
            here) so the same worker definition works against a real provider or a
            `MockBackend` in tests.
    """

    name: str
    area: str
    system_prompt: str
    backend: ModelBackend

    async def findings(self, contract: str) -> list[Finding]:
        """Audit one contract for this specialist's clause area.

        Sends ``[system_prompt, contract + return-instruction]`` to the backend at
        ``temperature=0.0`` and parses the completion into findings. Fail-soft by
        construction: `parse_findings` turns any non-conforming output (or an empty
        ``[]`` when the area is absent) into an empty list, so a misbehaving model
        produces no spurious payable work rather than raising.

        Args:
            contract: The full contract text to audit.

        Returns:
            The parsed findings, each tagged with ``worker == self.name``. May be empty.
        """
        messages = [
            Message.system(self.system_prompt),
            Message.user(contract + "\n\nReturn your findings now as the JSON array."),
        ]
        result = await self.backend.complete(messages, temperature=0.0, max_tokens=2000)
        return parse_findings(result.text, self.name)


# A static check that the worker honours the protocol (no runtime cost; mypy-visible).
_: type[Specialist] = SpecialistWorker


# ---------------------------------------------------------------------------
# Prompt engineering
# ---------------------------------------------------------------------------

# Shared output contract — appended to every specialist's area-specific brief so the
# JSON shape, the "one checkable assertion per finding" rule, and the no-fabrication
# rule are stated identically for all six (and exactly match what `parse_findings`
# consumes: a top-level array of {clause_ref, claim, severity}).
_OUTPUT_CONTRACT = """\
HOW TO REPORT
- Read the ENTIRE contract before writing anything — relevant terms may be defined in \
one section and applied in another, or buried in schedules, recitals, or definitions.
- Audit ONLY your assigned clause area. Ignore every other kind of clause; another \
specialist owns it. Do not comment on, summarise, or flag anything outside your area.
- Output a single JSON ARRAY. Each element is exactly:
    {"clause_ref": "<section number or '' if none>", "claim": "<one assertion>", \
"severity": "low|medium|high"}
- `claim` MUST be ONE discrete, checkable assertion about THIS contract — something a \
verifier can confirm or refute by reading the cited text. Be precise and quotable, \
e.g. "Clause 7.1 caps Vendor's aggregate liability at the fees paid in the prior 12 \
months". One assertion per finding: split compound observations into separate findings.
- Anchor each claim to the contract. Put the governing section number in `clause_ref` \
("" only when the contract gives no number). Prefer the contract's own wording.
- `severity` is the BUSINESS RISK to the party the term operates against: \
"high" = materially harmful / one-sided / unbounded exposure; "medium" = notable but \
bounded; "low" = minor or routine.
- DO NOT FABRICATE. Report only terms actually present in the text. If your clause \
area does not appear in this contract, return exactly: []
- Output ONLY the JSON array. No prose, no commentary, no markdown code fences."""


def _build_prompt(role: str, focus: str) -> str:
    """Compose a specialist system prompt from an area-specific brief + the shared
    output contract.

    Args:
        role: One-line statement of who the specialist is and its single mandate.
        focus: A bulleted list of the specific terms/risks to hunt for in-area.

    Returns:
        The full system prompt string.
    """
    return f"{role}\n\n{focus}\n\n{_OUTPUT_CONTRACT}"


_LIABILITY_PROMPT = _build_prompt(
    "You are a meticulous commercial-contracts attorney auditing ONLY the LIABILITY "
    "provisions of the contract below. You do nothing else.",
    "WHAT TO AUDIT (liability only):\n"
    "- Limitation-of-liability caps: the cap amount, how it is calculated (e.g. fees "
    "paid in a trailing period, a fixed sum, a multiple), and which party it protects.\n"
    "- Exclusions/disclaimers of damages: consequential, indirect, incidental, "
    "special, punitive, lost profits, lost data — and which party they shield.\n"
    "- Carve-outs from the cap or exclusions (e.g. liability cap does NOT apply to "
    "breach of confidentiality, IP infringement, indemnity, gross negligence, fraud).\n"
    "- Asymmetry: caps/exclusions that protect one party but not the other.\n"
    "- Uncapped or unlimited liability, and any 'as-is' / warranty disclaimers that "
    "shift loss.\n"
    "Flag missing or one-sided protection as risk; flag an unbounded cap as high risk.",
)

_IP_PROMPT = _build_prompt(
    "You are a meticulous intellectual-property attorney auditing ONLY the "
    "INTELLECTUAL-PROPERTY provisions of the contract below. You do nothing else.",
    "WHAT TO AUDIT (IP only):\n"
    "- Ownership of IP: pre-existing/background IP, and ownership of work product, "
    "deliverables, and any newly created/foreground IP — who owns what.\n"
    "- Assignments: present assignments of rights, assignment of inventions, and "
    "obligations to assist with perfecting title.\n"
    "- Licenses: scope (exclusive/non-exclusive), territory, duration, "
    "sublicensability, revocability, and any feedback/derivative-works grants.\n"
    "- Retained rights and residual-knowledge clauses.\n"
    "- Moral rights, third-party/open-source IP, and IP warranties of "
    "non-infringement.\n"
    "Flag broad or perpetual assignments away from a party, and overbroad licenses, "
    "as elevated risk.",
)

_TERMINATION_PROMPT = _build_prompt(
    "You are a meticulous commercial-contracts attorney auditing ONLY the "
    "TERMINATION, TERM, and RENEWAL provisions of the contract below. You do nothing "
    "else.",
    "WHAT TO AUDIT (termination/term only):\n"
    "- Termination for cause vs for convenience: who may terminate, on what grounds.\n"
    "- Notice periods: required notice length to terminate or to prevent renewal.\n"
    "- Cure periods: the window to cure a breach before termination is effective.\n"
    "- Initial term length and renewal mechanics: auto-renewal vs manual, "
    "evergreen/rolling terms, and non-renewal notice deadlines.\n"
    "- Effects of termination: survival of clauses, wind-down, transition assistance, "
    "return/deletion of materials, and any termination fees or penalties.\n"
    "Flag auto-renewal with a short/early opt-out window, one-sided termination "
    "rights, and the absence of a cure period as elevated risk.",
)

_TAX_PROMPT = _build_prompt(
    "You are a meticulous tax counsel auditing ONLY the TAX provisions of the "
    "contract below. You do nothing else.",
    "WHAT TO AUDIT (tax only):\n"
    "- Allocation of tax responsibility: which party bears sales/use/VAT/GST and "
    "other transaction taxes, and whether amounts are stated inclusive or exclusive "
    "of tax.\n"
    "- Gross-up obligations: whether payments must be grossed up so the payee "
    "receives the full amount net of taxes.\n"
    "- Withholding taxes: who bears withholding, and any obligation to provide "
    "tax forms/certificates or to cooperate to reduce withholding.\n"
    "- Each party's responsibility for its OWN income/franchise taxes.\n"
    "- Tax indemnities or representations specific to tax treatment.\n"
    "Flag clauses that shift another party's tax burden onto a party, and gross-up "
    "obligations, as elevated risk.",
)

_DATA_PRIVACY_PROMPT = _build_prompt(
    "You are a meticulous data-protection and privacy attorney auditing ONLY the "
    "DATA, PRIVACY, CONFIDENTIALITY, and SECURITY provisions of the contract below. "
    "You do nothing else.",
    "WHAT TO AUDIT (data/privacy/confidentiality/security only):\n"
    "- Permitted use of data: how each party may use, process, retain, aggregate, or "
    "share the other's data (including any rights to use data to train models or for "
    "the provider's own purposes).\n"
    "- Confidentiality: definition of Confidential Information, permitted "
    "disclosures, exclusions, and duration of the obligation.\n"
    "- Security safeguards: required technical/organisational measures, encryption, "
    "breach-notification obligations, and audit rights.\n"
    "- Data subject / data rights: ownership of data, deletion/return on "
    "termination, data portability, and compliance with privacy law (e.g. GDPR/CCPA, "
    "DPA/SCCs, sub-processor controls).\n"
    "Flag broad data-use grants, weak/absent breach notice, and indefinite or "
    "missing confidentiality terms as elevated risk.",
)

_INDEMNITY_PROMPT = _build_prompt(
    "You are a meticulous commercial-contracts attorney auditing ONLY the "
    "INDEMNIFICATION provisions of the contract below. You do nothing else. "
    "(Liability caps and disclaimers are a different specialist's job — touch them "
    "ONLY where an indemnity is expressly carved out of, or subject to, them.)",
    "WHAT TO AUDIT (indemnity only):\n"
    "- Who indemnifies whom, and for what triggers (third-party claims, IP "
    "infringement, data breach, bodily injury/property damage, breach of contract, "
    "violations of law).\n"
    "- Scope: whether the indemnity covers defense costs, settlements, attorneys' "
    "fees, and direct first-party losses vs only third-party claims.\n"
    "- Carve-outs and exceptions (e.g. no indemnity to the extent caused by the "
    "indemnified party's own negligence or modifications).\n"
    "- Indemnity caps or whether the indemnity is expressly excluded from the "
    "liability cap (i.e. effectively uncapped).\n"
    "- Procedure: notice, control of defense, and consent-to-settle requirements.\n"
    "- Asymmetry: one-way indemnities running against a single party.\n"
    "Flag uncapped, one-sided, or broadly scoped indemnities as elevated risk.",
)


# ---------------------------------------------------------------------------
# Registry + factory
# ---------------------------------------------------------------------------

#: The canonical pool definition: one (name, area, system_prompt) triple per
#: specialist. `name` is the stable worker id stamped onto findings; keep these unique.
SPECIALISTS: list[tuple[str, str, str]] = [
    (
        "liability",
        "liability caps, limitations, and disclaimers of damages",
        _LIABILITY_PROMPT,
    ),
    (
        "ip",
        "IP ownership, licenses, and assignment",
        _IP_PROMPT,
    ),
    (
        "termination",
        "termination rights, notice/cure periods, and renewal/non-renewal",
        _TERMINATION_PROMPT,
    ),
    (
        "tax",
        "tax responsibility, gross-up, and withholding",
        _TAX_PROMPT,
    ),
    (
        "data_privacy",
        "data use, confidentiality, security safeguards, and data rights",
        _DATA_PRIVACY_PROMPT,
    ),
    (
        "indemnity",
        "indemnification obligations, carve-outs, and indemnity caps",
        _INDEMNITY_PROMPT,
    ),
]


def make_pool_specialists(provider: str, model: str) -> list[SpecialistWorker]:
    """Build all six specialists on one shared backend.

    The model id is supplied by the caller and applied uniformly to every specialist;
    it is NEVER hardcoded here. The backend is constructed once and shared by all six
    workers (they only read from it, so sharing is safe and avoids redundant wiring).

    The shape — derive a per-specialist backend inside the loop — is deliberately kept
    so a future per-specialist model map (e.g. a cheaper model for routine areas, a
    stronger one for liability/indemnity) can be slotted in by varying `model` per
    entry without changing the call site.

    Args:
        provider: A provider key known to `make_backend` (e.g. ``"aimlapi"``).
        model: The model id to run every specialist on. Required; not hardcoded.

    Returns:
        Six `SpecialistWorker`s, one per entry in `SPECIALISTS`, in registry order.

    Raises:
        ValueError: If `provider` is unknown (propagated from `make_backend`).
        RuntimeError: If the provider's API key env var is unset (from `make_backend`).
    """
    backend = make_backend(provider, model)
    return [
        SpecialistWorker(name=name, area=area, system_prompt=system_prompt, backend=backend)
        for name, area, system_prompt in SPECIALISTS
    ]
