"""Swarm variant. Comparison only, nothing real runs through here.

Each agent picks its own handoff, so routing state ends up smeared across every
agent that touched the case. compare.py measures that against the supervisor.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from adjudication.domain.criteria import evaluate
from adjudication.runtime import guardrails as g
from adjudication.runtime.audit import AuditLog


@dataclass
class Handoff:
    frm: str
    to: str
    reason: str


@dataclass
class SwarmResult:
    decision: str
    handoffs: list[Handoff] = field(default_factory=list)
    # Routing rationale lives inside each agent, keyed by agent name.
    local_state: dict[str, dict] = field(default_factory=dict)

    @property
    def routing_holders(self) -> int:
        """How many components you have to interrogate to explain the outcome."""
        return len(self.local_state)


def run_swarm(case_id: str, narrative: str, tier: str, audit: AuditLog) -> SwarmResult:
    res = SwarmResult(decision="")

    # screener picks its own next hop
    gi = g.check_input(narrative)
    res.local_state["screener"] = {"allowed": gi.allowed, "reason": gi.reason}
    audit.append(case_id, "swarm:screener", "screened", {"allowed": gi.allowed})
    if not gi.allowed:
        res.handoffs.append(Handoff("screener", "officer", gi.reason))
        res.decision = "REFER_TO_OFFICER"
        return res
    res.handoffs.append(Handoff("screener", "assessor", "input clean"))

    # so does the assessor
    findings = evaluate(narrative)
    unmet = [f.criterion_code for f in findings if f.satisfied is False]
    unknown = [f.criterion_code for f in findings if f.satisfied is None]
    res.local_state["assessor"] = {"unmet": unmet, "unknown": unknown}
    audit.append(case_id, "swarm:assessor", "assessed", {"unmet": unmet})
    if unmet:
        res.handoffs.append(Handoff("assessor", "officer", f"unmet {unmet}"))
        res.decision = "REFER_TO_OFFICER"
        return res
    if unknown:
        res.handoffs.append(Handoff("assessor", "clarifier", f"unknown {unknown}"))
        res.local_state["clarifier"] = {"ask": unknown}
        audit.append(case_id, "swarm:clarifier", "requested_information", {"items": unknown})
        res.decision = "REQUEST_INFORMATION"
        return res

    res.handoffs.append(Handoff("assessor", "issuer", "all criteria met"))
    res.local_state["issuer"] = {"tier": tier}
    audit.append(case_id, "swarm:issuer", "granted", {})
    res.decision = "GRANT"
    return res
