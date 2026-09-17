"""Adjudication graph.

    intake -> guard_input -> retrieve -> guard_context -> assess -> supervisor
                                                       -> decide | escalate

Supervisor rather than swarm, for auditability (ADR-0002). escalate() suspends
via interrupt(), so the process can exit and pick up again from the checkpoint.
"""

from __future__ import annotations

import datetime as dt

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import RetryPolicy, interrupt

from adjudication.domain.clock import Clock
from adjudication.domain.criteria import evaluate
from adjudication.domain.model import RiskTier
from adjudication.retrieval.hybrid import Doc, HybridRetriever
from adjudication.runtime import guardrails as g
from adjudication.runtime.audit import AuditLog
from adjudication.runtime.redaction import redact

from .state import CaseState


def build_graph(corpus: list[Doc], audit: AuditLog, now: dt.datetime | None = None):
    retriever = HybridRetriever(corpus)
    NOW = now or dt.datetime.now(dt.UTC)

    def intake(state: CaseState) -> CaseState:
        r = redact(state["narrative"])
        audit.append(state["case_id"], "system:intake", "received",
                     {"risk_tier": state.get("risk_tier"), "redactions": len(r.mapping)})
        return {"narrative_redacted": r.text, "redaction_map": r.mapping,
                "attempts": 0, "trace": ["intake"]}

    def guard_input(state: CaseState) -> CaseState:
        res = g.check_input(state["narrative_redacted"])
        audit.append(state["case_id"], "system:guard_input", "screened",
                     {"allowed": res.allowed, "reason": res.reason})
        out: CaseState = {"trace": ["guard_input"],
                          "guard_events": [{"layer": "input", "allowed": res.allowed,
                                            "reason": res.reason}]}
        if not res.allowed:
            out["human_required"] = True
            out["escalation_reason"] = f"input guardrail: {res.reason}"
        return out

    def retrieve(state: CaseState) -> CaseState:
        hits = retriever.retrieve(state["narrative_redacted"], top_k=3)
        docs = [{"doc_id": i, "score": round(s, 4),
                 "text": next(d.text for d in corpus if d.doc_id == i)} for i, s in hits]
        audit.append(state["case_id"], "system:retrieve", "documents_selected",
                     {"doc_ids": [d["doc_id"] for d in docs]})
        return {"retrieved": docs, "trace": ["retrieve"]}

    def guard_context(state: CaseState) -> CaseState:
        res = g.check_context([d["text"] for d in state.get("retrieved", [])])
        audit.append(state["case_id"], "system:guard_context", "screened",
                     {"allowed": res.allowed, "critical": res.critical, "reason": res.reason})
        out: CaseState = {"trace": ["guard_context"],
                          "guard_events": [{"layer": "context", "allowed": res.allowed,
                                            "critical": res.critical, "reason": res.reason}]}
        if not res.allowed:
            out["human_required"] = True
            out["escalation_reason"] = f"context guardrail: {res.reason}"
        return out

    def assess(state: CaseState) -> CaseState:
        findings = evaluate(state["narrative_redacted"])
        payload = [{"criterion_code": f.criterion_code, "satisfied": f.satisfied,
                    "rationale": f.rationale, "grounded": f.grounded} for f in findings]
        audit.append(state["case_id"], "system:assess", "criteria_evaluated",
                     {"unmet": [f.criterion_code for f in findings if f.satisfied is False],
                      "undetermined": [f.criterion_code for f in findings if f.satisfied is None]})
        return {"findings": payload, "trace": ["assess"]}

    def supervisor(state: CaseState) -> CaseState:
        """All routing decided here. One decision, one audit record."""
        findings = state.get("findings", [])
        unmet = [f for f in findings if f["satisfied"] is False]
        unknown = [f for f in findings if f["satisfied"] is None]
        tier = RiskTier(state.get("risk_tier", "STANDARD"))
        clock = Clock(NOW, tier)

        if state.get("human_required"):
            decision, why = "REFER_TO_OFFICER", state.get("escalation_reason") or "guardrail"
        elif tier is RiskTier.COMPLEX:
            decision, why = "REFER_TO_OFFICER", "complex tier always sees an officer"
        elif unmet:
            # never machine-REFUSE. unmet goes to a human.
            decision, why = "REFER_TO_OFFICER", f"unmet criteria {[f['criterion_code'] for f in unmet]}"
        elif unknown:
            decision, why = "REQUEST_INFORMATION", f"undetermined {[f['criterion_code'] for f in unknown]}"
        elif clock.must_hand_over(NOW):
            decision, why = "REFER_TO_OFFICER", "automation budget exhausted"
        else:
            decision, why = "GRANT", "all mandatory criteria satisfied"

        audit.append(state["case_id"], "system:supervisor", "routed",
                     {"decision": decision, "why": why,
                      "statutory_deadline": clock.statutory_deadline.isoformat()})
        return {"decision": decision, "rationale": why,
                "escalation_reason": why if decision == "REFER_TO_OFFICER" else None,
                "trace": [f"supervisor:{decision}"]}

    def decide(state: CaseState) -> CaseState:
        grounded = all(f["satisfied"] is not None for f in state.get("findings", []))
        res = g.check_action(state["decision"], grounded, state.get("human_required", False))
        audit.append(state["case_id"], "system:guard_action", "screened",
                     {"allowed": res.allowed, "reason": res.reason})
        if not res.allowed:
            # action layer wins over the supervisor
            return {"decision": "REFER_TO_OFFICER",
                    "escalation_reason": f"action guardrail: {res.reason}",
                    "guard_events": [{"layer": "action", "allowed": False, "reason": res.reason}],
                    "trace": ["decide:overridden"]}
        return {"guard_events": [{"layer": "action", "allowed": True, "reason": "clean"}],
                "trace": ["decide"]}

    def escalate(state: CaseState) -> CaseState:
        audit.append(state["case_id"], "system:escalate", "suspended_for_officer",
                     {"reason": state.get("escalation_reason")})
        officer = interrupt({"case_id": state["case_id"],
                             "reason": state.get("escalation_reason"),
                             "findings": state.get("findings"),
                             "ask": "GRANT, REFUSE or REQUEST_INFORMATION"})
        audit.append(state["case_id"], f"officer:{officer.get('officer_id','unknown')}",
                     "decided", {"decision": officer.get("decision")})
        return {"officer_decision": officer.get("decision"),
                "decision": officer.get("decision"),
                "rationale": officer.get("rationale", "officer decision"),
                "trace": ["escalate:resumed"]}

    def route_after_decide(state: CaseState) -> str:
        return "escalate" if state["decision"] == "REFER_TO_OFFICER" else END

    sg = StateGraph(CaseState)
    retry = RetryPolicy(max_attempts=3, initial_interval=0.05, backoff_factor=2.0)
    sg.add_node("intake", intake, retry_policy=retry)
    sg.add_node("guard_input", guard_input)
    sg.add_node("retrieve", retrieve, retry_policy=retry)
    sg.add_node("guard_context", guard_context)
    sg.add_node("assess", assess)
    sg.add_node("supervisor", supervisor)
    sg.add_node("decide", decide)
    sg.add_node("escalate", escalate)

    sg.add_edge(START, "intake")
    sg.add_edge("intake", "guard_input")
    sg.add_edge("guard_input", "retrieve")
    sg.add_edge("retrieve", "guard_context")
    sg.add_edge("guard_context", "assess")
    sg.add_edge("assess", "supervisor")
    sg.add_edge("supervisor", "decide")
    sg.add_conditional_edges("decide", route_after_decide, {"escalate": "escalate", END: END})
    sg.add_edge("escalate", END)

    return sg.compile(checkpointer=InMemorySaver())
