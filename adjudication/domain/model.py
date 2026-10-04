"""Permit adjudication domain types.

The system recommends GRANT and never issues REFUSE. A wrong grant can be
revoked. A wrong refusal costs the applicant a build season. Enforced in three
places, see ADR-0001.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from enum import StrEnum


class Decision(StrEnum):
    GRANT = "GRANT"
    REFUSE = "REFUSE"                 # never machine-issued
    REFER_TO_OFFICER = "REFER_TO_OFFICER"
    REQUEST_INFORMATION = "REQUEST_INFORMATION"


class RiskTier(StrEnum):
    """Drives evaluation depth and approval requirements. Not model choice."""
    ROUTINE = "ROUTINE"               # fence, shed, signage
    STANDARD = "STANDARD"             # extension, change of use
    COMPLEX = "COMPLEX"               # structural, listed building, flood zone


@dataclass(frozen=True)
class Criterion:
    code: str
    title: str
    text: str
    mandatory: bool = True


@dataclass(frozen=True)
class Evidence:
    """A citation. `locator` must resolve back to a real document span."""
    document_id: str
    locator: str
    quote: str

    def __post_init__(self) -> None:
        if not self.quote.strip():
            raise ValueError("evidence quote may not be empty")


@dataclass
class Finding:
    criterion_code: str
    satisfied: bool | None          # None = could not determine
    rationale: str
    evidence: list[Evidence] = field(default_factory=list)

    @property
    def grounded(self) -> bool:
        """No evidence means the finding cannot carry an automated grant."""
        return bool(self.evidence)


@dataclass
class Application:
    case_id: str
    applicant_ref: str
    permit_type: str
    risk_tier: RiskTier
    received_at: dt.datetime
    documents: list[str] = field(default_factory=list)
    narrative: str = ""


@dataclass
class Outcome:
    case_id: str
    decision: Decision
    findings: list[Finding]
    rationale: str
    decided_at: dt.datetime
    decided_by: str                  # "system" or an officer id
    escalation_reason: str | None = None
