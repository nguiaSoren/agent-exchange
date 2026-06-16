"""The five insurance-claim-review specialists + a sample policy & claim — the worker
side of the Agent Exchange, specialised for a HIGH-STAKES, REGULATED domain: auditing an
insurance **adjuster's payout determination** against the two governing source documents,
the **policy** and the **claim**.

Each specialist is a single-area auditor: it reads BOTH the policy and the claim (supplied
as one delimited document) but reports ONLY on its own risk area (coverage scope,
exclusions, limits/deductible, claim validity, or payout calculation). It emits a JSON
array of **findings**, each one a discrete, checkable assertion the downstream verifier can
confirm against the source text — that verification is what makes the work payable, so a
vague or fabricated coverage assertion is worthless by construction. In a regulated domain
that is exactly the point: a fabricated "the policy covers X" is the costly failure mode,
and the verifier withholds pay for it.

This module mirrors `nda_specialists.py` exactly: the same `(name, area, system_prompt)`
triple shape, the same shared output contract (via `_build_prompt` from `specialist.py`),
and the same "one checkable claim per finding, no fabrication" discipline. The roster factory lives
in `job_types.py` (`roster_for("insurance-claim", ...)`), which reuses the same
`SpecialistWorker` + `make_backend` wiring as the contract-audit and NDA pools.

Public API:
  - `INSURANCE_SPECIALISTS` — the registry of (name, area, system_prompt) triples (5).
  - `SAMPLE_INSURANCE_POLICY` — a short, realistic homeowners-style policy.
  - `SAMPLE_INSURANCE_CLAIM`  — a short claim + the adjuster's payout determination, written
    so that the determination asserts a coverage the policy does NOT contain (the seedable
    fabrication target: flood damage, which the policy expressly excludes).

Design notes:
  - The model id is NEVER hardcoded — it flows in from the caller through the roster
    factory in `job_types.py`.
  - The prompts do all the steering; the output contract is identical to the
    contract-audit / NDA specialists' so `parse_findings` consumes them unchanged.
  - The specialists audit BOTH sources at once (policy + claim concatenated), so the
    existing single-document verifier path carries this kind WITHOUT new machinery; the
    multi-source `CrossSourceVerifier` showcase is wired separately (see the server).
"""

from __future__ import annotations

# Reuse the contract-audit specialists' shared output contract (via the prompt builder) so
# the insurance roster emits the EXACT same JSON shape `parse_findings` already consumes.
from .specialist import _build_prompt

# ---------------------------------------------------------------------------
# Prompt engineering — one area-specific brief per insurance-claim risk area
# ---------------------------------------------------------------------------

_COVERAGE_SCOPE_PROMPT = _build_prompt(
    "You are an insurance-claim-review specialist for COVERAGE SCOPE — what perils and "
    "losses the policy actually insures. You audit the supplied POLICY and CLAIM text "
    "ONLY for whether the loss the adjuster paid is within the policy's coverage grant. "
    "You do nothing else.",
    "WHAT TO AUDIT (coverage scope only):\n"
    "- The insuring agreement: which perils/causes of loss are covered (named-peril vs "
    "all-risk), and whether the loss described in the claim falls within that grant.\n"
    "- Whether the adjuster's payout determination asserts coverage for a peril the "
    "policy actually grants — versus a peril the policy never mentions or insures.\n"
    "- The covered property/persons and any conditions on coverage attaching (e.g. the "
    "loss must occur at the insured location, during the policy period).\n"
    "- Coverage parts (dwelling, personal property, liability) and which one the claim "
    "is paid under.\n"
    "MOST IMPORTANT: if the adjuster's determination claims the policy COVERS a peril "
    "that the policy text does not grant (or expressly excludes), flag that as HIGH risk "
    "— a fabricated coverage assertion is the costly failure mode in a paid claim.",
)

_EXCLUSIONS_PROMPT = _build_prompt(
    "You are an insurance-claim-review specialist for EXCLUSIONS — the perils and "
    "circumstances the policy carves OUT of coverage. You audit the supplied POLICY and "
    "CLAIM text ONLY for whether an exclusion bars (or limits) the paid loss. You do "
    "nothing else.",
    "WHAT TO AUDIT (exclusions only):\n"
    "- Each express exclusion in the policy (e.g. flood, earth movement, wear and tear, "
    "intentional acts, war) and whether the claimed loss falls within any of them.\n"
    "- Whether the adjuster's determination pays a loss that an exclusion plainly bars, "
    "or silently ignores an applicable exclusion.\n"
    "- Anti-concurrent-causation language and whether an excluded cause contributed to "
    "the loss.\n"
    "- Exceptions to exclusions (a carve-back that restores coverage) and whether one "
    "applies.\n"
    "Flag a payout that an express exclusion bars as HIGH risk; flag an exclusion the "
    "determination failed to consider as elevated risk.",
)

_LIMITS_DEDUCTIBLE_PROMPT = _build_prompt(
    "You are an insurance-claim-review specialist for LIMITS & DEDUCTIBLE — the dollar "
    "ceilings and the insured's retention. You audit the supplied POLICY and CLAIM text "
    "ONLY for whether the paid amount respects the policy's limits and deductible. You do "
    "nothing else.",
    "WHAT TO AUDIT (limits & deductible only):\n"
    "- The applicable coverage limit (per-occurrence, per-item, sub-limits for specific "
    "categories) and whether the payout exceeds it.\n"
    "- The deductible: its amount, whether it was correctly subtracted from the loss "
    "before payment, and any special/percentage deductible.\n"
    "- Sub-limits and special caps (e.g. a low cap on jewelry, electronics, cash) and "
    "whether the paid category is constrained by one.\n"
    "- Coinsurance or replacement-cost vs actual-cash-value adjustments that change the "
    "payable amount.\n"
    "Flag a payout that exceeds the limit, or that omits the deductible, as HIGH risk.",
)

_CLAIM_VALIDITY_PROMPT = _build_prompt(
    "You are an insurance-claim-review specialist for CLAIM VALIDITY — whether the claim "
    "itself was properly made and is well-founded. You audit the supplied POLICY and "
    "CLAIM text ONLY for procedural and factual validity. You do nothing else.",
    "WHAT TO AUDIT (claim validity only):\n"
    "- Timeliness: whether the loss was reported within any notice deadline the policy "
    "sets, and whether the claim is within the policy period.\n"
    "- The insured's duties after loss (proof of loss, documentation, cooperation, "
    "mitigation) and whether the claim record shows them met.\n"
    "- Internal consistency: whether the date, cause, location, and amount of loss stated "
    "in the claim are mutually consistent and consistent with the policy's coverage.\n"
    "- Any indication of misrepresentation or an obviously unsupported loss amount.\n"
    "Flag a late-reported claim, a missing proof of loss, or an internally inconsistent "
    "claim as elevated risk.",
)

_PAYOUT_CALCULATION_PROMPT = _build_prompt(
    "You are an insurance-claim-review specialist for PAYOUT CALCULATION — the ARITHMETIC "
    "of the adjuster's determination. You audit the supplied POLICY and CLAIM text ONLY "
    "for whether the paid number is computed correctly from the loss, the deductible, and "
    "the limit. You do nothing else.",
    "WHAT TO AUDIT (payout calculation only):\n"
    "- The stated loss amount, the deductible subtracted, and the resulting net payout — "
    "whether the arithmetic is correct (loss − deductible, capped at the limit).\n"
    "- Whether depreciation / actual-cash-value was applied where the policy requires it, "
    "and whether replacement-cost holdback (if any) is handled.\n"
    "- Whether any sub-limit or coinsurance penalty was applied to the figure.\n"
    "- Whether the determination's payout figure matches what the policy terms produce on "
    "the claimed loss.\n"
    "Flag an arithmetic error, an un-applied deductible, or a figure exceeding the limit "
    "as HIGH risk.",
)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

#: The canonical insurance-claim pool: one (name, area, system_prompt) triple per
#: specialist. `name` is the stable worker id stamped onto findings; keep these unique.
#: Mirrors `nda_specialists.NDA_SPECIALISTS` in shape and discipline.
INSURANCE_SPECIALISTS: list[tuple[str, str, str]] = [
    (
        "coverage_scope",
        "the insuring agreement and whether the paid loss is within coverage",
        _COVERAGE_SCOPE_PROMPT,
    ),
    (
        "exclusions",
        "policy exclusions and whether one bars the paid loss",
        _EXCLUSIONS_PROMPT,
    ),
    (
        "limits_deductible",
        "coverage limits, sub-limits, and the deductible",
        _LIMITS_DEDUCTIBLE_PROMPT,
    ),
    (
        "claim_validity",
        "procedural and factual validity of the claim",
        _CLAIM_VALIDITY_PROMPT,
    ),
    (
        "payout_calculation",
        "the arithmetic of the adjuster's payout determination",
        _PAYOUT_CALCULATION_PROMPT,
    ),
]


# ---------------------------------------------------------------------------
# Sample documents — a realistic policy + a claim with a seedable fabrication target
# ---------------------------------------------------------------------------

#: A short, concrete homeowners-style policy. Named perils, an explicit FLOOD exclusion, a
#: stated limit and deductible — so every specialist can produce checkable claims, and so a
#: "flood is covered" assertion in the determination is provably FALSE against this text.
SAMPLE_INSURANCE_POLICY: str = """\
HOMEOWNERS POLICY HO-3 — SUMMARY OF TERMS

Policyholder: Dana Reyes      Policy No.: HR-44821
Insured Location: 14 Linden Court      Policy Period: Jan 1, 2025 – Jan 1, 2026

1. INSURING AGREEMENT. We insure the dwelling and personal property at the Insured
Location against direct physical loss caused by the following NAMED PERILS only: fire and
lightning; windstorm and hail; explosion; theft; and accidental discharge or overflow of
water from a plumbing, heating, or air-conditioning system within the dwelling.

2. COVERAGE LIMITS. Coverage A (Dwelling) limit: $250,000. Coverage C (Personal Property)
limit: $100,000, subject to a special sub-limit of $2,500 for jewelry and watches.

3. DEDUCTIBLE. A $1,000 deductible applies to each covered loss and is subtracted from the
loss amount before payment.

4. EXCLUSIONS. We do NOT cover loss caused directly or indirectly by: (a) FLOOD, surface
water, overflow of a body of water, or storm surge, whether or not driven by wind; (b)
earth movement, including earthquake and mudflow; (c) wear and tear, deterioration, or
gradual seepage; or (d) intentional acts of an insured. These exclusions apply regardless
of any other cause contributing concurrently to the loss.

5. DUTIES AFTER LOSS. The insured must give us prompt notice of a loss, and in no event
later than sixty (60) days after the loss, and must submit a signed proof of loss.
"""

#: The claim record + the adjuster's payout determination. The loss is wind-driven roof
#: damage (a covered NAMED PERIL — windstorm) AND interior FLOODING from rising surface
#: water (an EXPRESSLY EXCLUDED peril). The adjuster's determination pays BOTH — the
#: flood portion is the SEEDED FABRICATION TARGET: a coverage assertion the policy text
#: (Exclusion 4(a)) flatly contradicts.
SAMPLE_INSURANCE_CLAIM: str = """\
CLAIM FILE — HR-44821

Date of Loss: Mar 14, 2025      Date Reported: Mar 18, 2025
Claimant: Dana Reyes      Insured Location: 14 Linden Court

DESCRIPTION OF LOSS. During a severe storm, high winds tore shingles and decking from the
dwelling's roof, allowing rain to enter and damage the attic and ceilings. Separately,
rising surface water from the overflowing creek behind the property entered the ground
floor and damaged flooring and personal property.

ITEMIZED LOSS.
- Roof and interior repair from wind/rain entry .......... $18,000
- Ground-floor flooring + property from rising water ..... $22,000

ADJUSTER'S PAYOUT DETERMINATION.
The wind-driven roof damage is a covered windstorm loss. The ground-floor water damage
from the overflowing creek is also covered under the policy's water-damage coverage. We
therefore pay the combined loss of $40,000, less the $1,000 deductible, for a net payout
of $39,000.
"""
