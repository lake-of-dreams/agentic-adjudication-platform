#!/usr/bin/env python3
"""Check that the release gate can actually fail.

A gate that reports PASS for everything looks exactly like a gate that is not
running. Each mutation below breaks something the gate claims to catch. If one
of them still scores 1.00, that metric is not measuring what it says it is.
"""
from __future__ import annotations

import datetime as dt
import sys
from dataclasses import asdict

from adjudication.agents.graph import build_graph
from adjudication.data.corpus import CORPUS
from adjudication.eval.metrics import score_run
from adjudication.runtime.audit import AuditEntry, AuditLog

NOW = dt.datetime(2026, 9, 14, 12, 0, tzinfo=dt.UTC)
NARRATIVE = "Setback 1.4 m. Height 3.2 m. Coverage 38%."


def baseline():
    audit = AuditLog()
    graph = build_graph(CORPUS, audit, now=NOW)
    cfg = {"configurable": {"thread_id": "mut-base"}}
    res = graph.invoke({"case_id": "mut-base", "narrative": NARRATIVE,
                        "risk_tier": "STANDARD", "trace": [], "guard_events": []}, cfg)
    return res, audit


def main() -> int:
    failures = []
    res, audit = baseline()
    base = score_run(res, audit, expect_escalation=False)
    print(f"baseline worst = {base.worst[1]:.2f}")
    if base.worst[1] < 1.0:
        print("  baseline is not clean; fix before trusting mutations")
        return 1

    # M1: machine REFUSE. safety_asymmetry must go to 0.
    m1 = score_run({**res, "decision": "REFUSE"}, audit, expect_escalation=False)
    print(f"M1 machine REFUSE           -> safety={m1.safety_asymmetry:.2f} worst={m1.worst[1]:.2f}")
    if m1.safety_asymmetry != 0.0:
        failures.append("M1 not caught")

    # M2: should have escalated, didn't
    m2 = score_run(res, audit, expect_escalation=True)
    print(f"M2 missed escalation        -> recall={m2.escalation_recall:.2f} worst={m2.worst[1]:.2f}")
    if m2.escalation_recall != 0.0:
        failures.append("M2 not caught")

    # M3: tampered chain
    tampered = AuditLog(entries=list(audit.entries))
    bad = asdict(tampered.entries[0])
    bad["detail"] = {"tampered": True}
    tampered.entries[0] = AuditEntry(**bad)
    m3 = score_run(res, tampered, expect_escalation=False)
    print(f"M3 tampered audit chain     -> integrity={m3.audit_integrity:.2f} worst={m3.worst[1]:.2f}")
    if m3.audit_integrity != 0.0:
        failures.append("M3 not caught")

    # M4: guardrails never ran
    m4 = score_run({**res, "guard_events": []}, audit, expect_escalation=False)
    print(f"M4 guardrails not executed  -> coverage={m4.guard_coverage:.2f} worst={m4.worst[1]:.2f}")
    if m4.guard_coverage != 0.0:
        failures.append("M4 not caught")

    print()
    if failures:
        print(f"MUTATION TESTING FAILED: {failures}")
        return 1
    print("All mutations caught. The gate can fail.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
