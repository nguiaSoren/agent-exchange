"""The six NDA-review specialists + a sample NDA — the worker side of the
Agent Exchange, specialised for non-disclosure agreements.

Each specialist is a single-area auditor: it reads the WHOLE NDA but reports ONLY
on its own risk area (confidentiality scope, term & survival, permitted use,
return/destruction, carve-outs/exclusions, or residuals & non-solicitation). It
emits a JSON array of **findings**, each one a discrete, checkable assertion the
downstream verifier can confirm against the NDA text — that verification is what
makes the work payable, so vague or fabricated claims are worthless by construction.

This module mirrors `specialist.py` exactly: same `(name, area, system_prompt)`
triple shape, the same shared output contract, and the same "one checkable claim
per finding, no fabrication" discipline. The roster factory for NDAs lives in
`job_types.py` (`roster_for("nda-review", ...)`), which reuses the same
`SpecialistWorker` and `make_backend` wiring as the contract-audit pool.

Public API:
  - `NDA_SPECIALISTS` — the registry of (name, area, system_prompt) triples (6).
  - `SAMPLE_NDA`      — a realistic mutual NDA, concrete enough that every clause
    yields checkable claims, so the NDA pipeline has a demo document to run on.

Design notes:
  - The model id is NEVER hardcoded — it flows in from the caller through the roster
    factory in `job_types.py`.
  - The prompts do all the steering; the output contract is identical to the
    contract-audit specialists' so `parse_findings` consumes them unchanged.
"""

from __future__ import annotations

# Reuse the contract-audit specialists' shared output contract and prompt builder so
# the NDA roster emits the EXACT same JSON shape `parse_findings` already consumes.
from .specialist import _OUTPUT_CONTRACT, _build_prompt

# ---------------------------------------------------------------------------
# Prompt engineering — one area-specific brief per NDA risk area
# ---------------------------------------------------------------------------

_CONFIDENTIALITY_SCOPE_PROMPT = _build_prompt(
    "You are an NDA-review specialist for CONFIDENTIALITY SCOPE — the definition of "
    "Confidential Information. Audit ONLY the supplied NDA text for how broadly or "
    "narrowly protected information is defined. You do nothing else.",
    "WHAT TO AUDIT (confidentiality scope / definition only):\n"
    "- The definition of 'Confidential Information': what categories it covers "
    "(technical, financial, business, customer data, trade secrets) and whether it is "
    "open-ended ('including but not limited to') or a closed list.\n"
    "- Whether protection requires information to be MARKED confidential, or to be "
    "identified as confidential within a stated number of days if disclosed orally.\n"
    "- Whether the definition reaches the existence of the agreement / the discussions "
    "themselves, and any derivatives, notes, or analyses made from disclosed material.\n"
    "- Mutuality: whether the definition protects both parties' information or only "
    "one party's (one-sided disclosure).\n"
    "- Vagueness or overbreadth: a definition so broad it sweeps in already-public or "
    "trivial information.\n"
    "Flag an overbroad/open-ended definition with no marking requirement, and a "
    "one-sided definition, as elevated risk.",
)

_TERM_SURVIVAL_PROMPT = _build_prompt(
    "You are an NDA-review specialist for TERM & SURVIVAL — how long the obligations "
    "last. Audit ONLY the supplied NDA text for durations. You do nothing else.",
    "WHAT TO AUDIT (term & survival only):\n"
    "- The term of the agreement itself (how long the parties may exchange "
    "information) versus the survival period of the confidentiality obligation after "
    "the agreement ends or terminates.\n"
    "- The exact duration of the confidentiality obligation: a fixed number of years, "
    "perpetual/indefinite, or 'until the information becomes public'.\n"
    "- Any longer or perpetual protection specifically for trade secrets, separate "
    "from the general survival period.\n"
    "- Whether termination of the agreement ends the duty to protect already-disclosed "
    "information, or whether that duty survives termination.\n"
    "- Asymmetry: different survival periods for each party's information.\n"
    "Flag an indefinite/perpetual obligation on ordinary (non-trade-secret) "
    "information, and the absence of any stated survival period, as elevated risk.",
)

_PERMITTED_USE_PROMPT = _build_prompt(
    "You are an NDA-review specialist for PERMITTED USE & NEED-TO-KNOW — what the "
    "receiving party may actually do with the information, and who may see it. Audit "
    "ONLY the supplied NDA text. You do nothing else.",
    "WHAT TO AUDIT (permitted use & need-to-know only):\n"
    "- The stated Purpose: whether use of the information is limited to a specific, "
    "defined purpose (e.g. 'evaluating a potential transaction') or is open-ended.\n"
    "- Need-to-know: whether disclosure within the receiving party is limited to "
    "employees/representatives who need it for the Purpose, and whether those "
    "representatives must be bound by equivalent confidentiality terms.\n"
    "- Onward-disclosure controls: whether affiliates, advisors, or subcontractors "
    "may receive the information and on what conditions, plus responsibility for "
    "representatives' breaches.\n"
    "- Express prohibitions: no reverse-engineering, no commercial exploitation, no "
    "use to compete, no copying beyond what the Purpose requires.\n"
    "- Whether the NDA grants any license or only a limited permission to use for the "
    "Purpose (a no-license clause).\n"
    "Flag an open-ended purpose, unrestricted onward disclosure, or the absence of a "
    "need-to-know limit as elevated risk.",
)

_RETURN_DESTRUCTION_PROMPT = _build_prompt(
    "You are an NDA-review specialist for RETURN-OR-DESTRUCTION of materials — what "
    "happens to the information when the relationship ends or on demand. Audit ONLY "
    "the supplied NDA text. You do nothing else.",
    "WHAT TO AUDIT (return or destruction only):\n"
    "- The trigger: whether return/destruction is required on termination, on "
    "completion of the Purpose, and/or on the disclosing party's written request.\n"
    "- Scope: whether the obligation covers originals, copies, derivatives, notes, "
    "and material stored electronically or in backups.\n"
    "- Method and proof: whether destruction must be certified in writing, and within "
    "what deadline return/destruction must occur.\n"
    "- Retention carve-outs: permitted retention for legal/regulatory/archival "
    "/automatic-backup reasons, and whether retained copies remain subject to "
    "confidentiality.\n"
    "- Whether the clause is mutual or binds only one party.\n"
    "Flag the absence of a return/destruction obligation, an unbounded deadline, or "
    "retained copies escaping continued confidentiality as elevated risk.",
)

_CARVE_OUTS_PROMPT = _build_prompt(
    "You are an NDA-review specialist for CARVE-OUTS / EXCLUSIONS — the categories of "
    "information that are NOT (or no longer) confidential, and the compelled-disclosure "
    "exception. Audit ONLY the supplied NDA text. You do nothing else.",
    "WHAT TO AUDIT (carve-outs / exclusions only):\n"
    "- The standard exclusions: information that is or becomes public through no fault "
    "of the receiving party; was already rightfully known before disclosure; is "
    "independently developed without use of the Confidential Information; or is "
    "rightfully received from a third party free of any confidentiality duty.\n"
    "- Whether each exclusion is present and worded normally, or is missing, narrowed, "
    "or broadened in a way that favours one party.\n"
    "- The required-by-law / compelled-disclosure exception: whether disclosure forced "
    "by law, court order, or regulator is permitted, and whether it is conditioned on "
    "prompt notice to the disclosing party and reasonable cooperation to seek "
    "protective treatment (so only the minimum required is disclosed).\n"
    "- Who bears the burden of proving an exclusion applies.\n"
    "Flag missing standard exclusions, or a compelled-disclosure clause with no "
    "notice/cooperation safeguard, as elevated risk.",
)

_RESIDUALS_NONSOLICIT_PROMPT = _build_prompt(
    "You are an NDA-review specialist for RESIDUALS & NON-SOLICITATION/NON-COMPETE — "
    "clauses that constrain the parties BEYOND mere confidentiality, or that weaken it "
    "via a residual-knowledge allowance. Audit ONLY the supplied NDA text. You do "
    "nothing else.",
    "WHAT TO AUDIT (residuals & non-solicitation/non-compete only):\n"
    "- Residuals clause: whether the receiving party may freely use general knowledge, "
    "skills, or ideas 'retained in unaided memory' — a clause that can quietly gut the "
    "confidentiality protection — and how broadly 'residuals' is defined.\n"
    "- Non-solicitation: any restriction on soliciting or hiring the other party's "
    "employees, customers, or suppliers, including its duration and breadth.\n"
    "- Non-compete / non-circumvention: any restriction on competing, on contacting "
    "the other party's contacts, or on pursuing the underlying opportunity directly.\n"
    "- Duration, geographic scope, and reasonableness/enforceability of any such "
    "restraint, and whether it is mutual or one-sided.\n"
    "- Whether these restraints properly belong in an NDA at all, or overreach beyond "
    "protecting confidential information.\n"
    "Flag a broad residuals clause, and any overbroad or one-sided "
    "non-solicit/non-compete, as elevated risk.",
)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

#: The canonical NDA pool definition: one (name, area, system_prompt) triple per
#: specialist. `name` is the stable worker id stamped onto findings; keep these
#: unique. Mirrors `specialist.SPECIALISTS` in shape and discipline.
NDA_SPECIALISTS: list[tuple[str, str, str]] = [
    (
        "confidentiality_scope",
        "definition and breadth of Confidential Information",
        _CONFIDENTIALITY_SCOPE_PROMPT,
    ),
    (
        "term_survival",
        "term of the agreement and survival period of the obligations",
        _TERM_SURVIVAL_PROMPT,
    ),
    (
        "permitted_use",
        "permitted use, defined purpose, and need-to-know disclosure",
        _PERMITTED_USE_PROMPT,
    ),
    (
        "return_destruction",
        "return or destruction of materials on termination or demand",
        _RETURN_DESTRUCTION_PROMPT,
    ),
    (
        "carve_outs",
        "standard exclusions and the required-by-law disclosure exception",
        _CARVE_OUTS_PROMPT,
    ),
    (
        "residuals_nonsolicit",
        "residual-knowledge allowance and non-solicitation/non-compete restraints",
        _RESIDUALS_NONSOLICIT_PROMPT,
    ),
]


# ---------------------------------------------------------------------------
# Sample document — a realistic mutual NDA for the demo pipeline
# ---------------------------------------------------------------------------

#: A concrete ~8-clause mutual NDA. Durations and carve-outs are specific so each
#: specialist can produce checkable claims (e.g. "Section 4 sets a 3-year survival
#: period" / "Section 5 omits an independent-development exclusion").
SAMPLE_NDA: str = """\
MUTUAL NON-DISCLOSURE AGREEMENT

This Mutual Non-Disclosure Agreement (the "Agreement") is entered into as of March 1,
2025 (the "Effective Date") by and between Northbridge Analytics, Inc., a Delaware
corporation ("Northbridge"), and Cedar Systems Ltd. ("Cedar"). Northbridge and Cedar
are each a "Party" and, when disclosing information, the "Disclosing Party," and when
receiving it, the "Receiving Party."

1. PURPOSE. The Parties wish to explore a potential business relationship concerning
the integration of Cedar's data-pipeline technology with Northbridge's analytics
platform (the "Purpose"), and in connection with the Purpose may disclose to each
other certain confidential and proprietary information.

2. CONFIDENTIAL INFORMATION. "Confidential Information" means any non-public
information disclosed by the Disclosing Party to the Receiving Party, in any form,
that is either marked or identified as "confidential" or "proprietary" at the time of
disclosure, or that a reasonable person would understand to be confidential given the
nature of the information and the circumstances of disclosure. Information disclosed
orally or visually shall be treated as Confidential Information if identified as
confidential at the time of disclosure and confirmed in writing as confidential within
thirty (30) days. Confidential Information includes the existence and terms of this
Agreement and the fact that discussions are taking place between the Parties.

3. PERMITTED USE. The Receiving Party shall use the Confidential Information solely for
the Purpose and for no other purpose. The Receiving Party may disclose Confidential
Information only to its employees, officers, directors, and professional advisors
(collectively, "Representatives") who have a need to know it for the Purpose and who
are bound by written obligations of confidentiality at least as protective as those in
this Agreement. The Receiving Party shall be responsible for any breach of this
Agreement by its Representatives. The Receiving Party shall not reverse-engineer,
decompile, or disassemble any Confidential Information.

4. TERM AND SURVIVAL. This Agreement shall commence on the Effective Date and continue
for two (2) years, unless earlier terminated by either Party upon thirty (30) days'
prior written notice. The Receiving Party's obligations of confidentiality and
non-use under this Agreement shall survive termination or expiration and shall remain
in effect for three (3) years from the date of disclosure of the relevant Confidential
Information; provided, however, that with respect to any Confidential Information that
constitutes a trade secret, such obligations shall continue for as long as the
information remains a trade secret under applicable law.

5. EXCLUSIONS. The obligations in this Agreement do not apply to information that the
Receiving Party can demonstrate: (a) is or becomes generally available to the public
through no act or omission of the Receiving Party; (b) was rightfully known to the
Receiving Party, without restriction, before its disclosure by the Disclosing Party;
(c) is independently developed by the Receiving Party without use of or reference to
the Confidential Information; or (d) is rightfully obtained by the Receiving Party from
a third party who is free to disclose it without restriction. The Receiving Party may
disclose Confidential Information to the extent required by law, regulation, or valid
court order, provided that it gives the Disclosing Party prompt written notice (where
legally permitted) and reasonable cooperation, at the Disclosing Party's expense, so
that the Disclosing Party may seek a protective order, and discloses only the portion
of Confidential Information legally required.

6. RETURN OR DESTRUCTION. Upon the Disclosing Party's written request, or upon
termination or expiration of this Agreement, the Receiving Party shall promptly, and
in any event within thirty (30) days, return or destroy all Confidential Information
in its possession, including all copies, notes, and derivatives thereof, and shall
certify such destruction in writing if requested. Notwithstanding the foregoing, the
Receiving Party may retain one (1) archival copy solely for legal and compliance
purposes and copies created by routine automated backup systems, provided that any
retained copies remain subject to the confidentiality obligations of this Agreement.

7. NO LICENSE. All Confidential Information remains the property of the Disclosing
Party. Nothing in this Agreement grants the Receiving Party any license or other right
in or to the Confidential Information, or any patent, copyright, trademark, or other
intellectual property right of the Disclosing Party, except the limited right to use
it for the Purpose. No warranty is made as to the accuracy or completeness of any
Confidential Information.

8. GENERAL. This Agreement shall be governed by and construed in accordance with the
laws of the State of Delaware, without regard to its conflict-of-laws principles. This
Agreement constitutes the entire agreement between the Parties regarding its subject
matter and supersedes all prior discussions. Neither Party is obligated to proceed
with any transaction. This Agreement may be amended only by a writing signed by both
Parties.
"""
