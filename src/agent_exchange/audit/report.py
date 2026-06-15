"""AuditReport — the end-to-end output of one contract audit (the pipeline contract).

Ties a worker's `Finding` to the verifier's `ClaimVerdict` (an `AuditedFinding`), plus
the `SettlementRuling` (how much the deliverable earns under the pay policy) and the
per-stage instrumentation that feeds the `/metrics` `JobTrace`. This is the locked
schema the pipeline subagent builds toward.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..verify.schema import ClaimVerdict, SettlementRuling, Verdict
from ..workers.finding import Finding


@dataclass(frozen=True, slots=True)
class AuditedFinding:
    """A worker's finding + the verifier's grade of its claim."""

    finding: Finding
    verdict: ClaimVerdict


@dataclass(frozen=True, slots=True)
class AuditReport:
    """One contract audit, end to end."""

    contract_id: str
    audited: tuple[AuditedFinding, ...]
    ruling: SettlementRuling
    timings_ms: dict[str, float] = field(default_factory=dict)   # per-stage (deliver/verify/...)
    total_cost_usd: float | None = None

    @property
    def n_findings(self) -> int:
        return len(self.audited)

    @property
    def n_high_risk(self) -> int:
        return sum(af.finding.severity == "high" for af in self.audited)

    @property
    def n_confirmed(self) -> int:
        return sum(af.verdict.verdict is Verdict.CONFIRMED for af in self.audited)

    @property
    def n_unsupported(self) -> int:
        return sum(af.verdict.verdict is Verdict.UNSUPPORTED for af in self.audited)
