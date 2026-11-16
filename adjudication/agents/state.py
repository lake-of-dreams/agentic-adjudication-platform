"""Graph state.

Every field has to survive a checkpoint round-trip. interrupt/resume writes this
to a store and reads it back in a different process, possibly days later when an
officer finally gets to the queue.
"""

from __future__ import annotations

import operator
from typing import Annotated, Any, Literal, TypedDict


class CaseState(TypedDict, total=False):
    case_id: str
    narrative: str
    narrative_redacted: str
    redaction_map: dict[str, str]
    risk_tier: str

    retrieved: list[dict[str, Any]]
    findings: list[dict[str, Any]]

    decision: Literal["GRANT", "REFUSE", "REFER_TO_OFFICER", "REQUEST_INFORMATION"]
    rationale: str
    escalation_reason: str | None

    # operator.add so parallel branches append rather than clobber.
    trace: Annotated[list[str], operator.add]
    guard_events: Annotated[list[dict[str, Any]], operator.add]

    human_required: bool
    officer_decision: str | None
    attempts: int
