"""Spans for a case's steps (ADR-0016): present, ordered, and free of case text."""
from __future__ import annotations

import datetime as dt
import json

import pytest

pytest.importorskip("opentelemetry.sdk")

from langgraph.types import Command  # noqa: E402
from opentelemetry import trace  # noqa: E402
from opentelemetry.sdk.trace import TracerProvider  # noqa: E402
from opentelemetry.sdk.trace.export import SimpleSpanProcessor  # noqa: E402
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter  # noqa: E402

from adjudication.agents.graph import build_graph  # noqa: E402
from adjudication.agents.officer import signed_reply  # noqa: E402
from adjudication.data.corpus import CORPUS  # noqa: E402
from adjudication.runtime.audit import AuditLog  # noqa: E402
from adjudication.runtime.jws import new_key  # noqa: E402

NOW = dt.datetime(2026, 9, 14, 12, 0, tzinfo=dt.UTC)
IDP = new_key()
_exporter = InMemorySpanExporter()
_provider = TracerProvider()
_provider.add_span_processor(SimpleSpanProcessor(_exporter))
trace.set_tracer_provider(_provider)


def run(narrative: str, case_id: str):
    _exporter.clear()
    graph = build_graph(CORPUS, AuditLog(), now=NOW, officer_keys={"idp-1": IDP.public_key()})
    cfg = {"configurable": {"thread_id": case_id}}
    res = graph.invoke({"case_id": case_id, "narrative": narrative, "risk_tier": "STANDARD",
                        "trace": [], "guard_events": []}, cfg)
    return res, graph, cfg


def test_a_granted_case_has_one_span_per_step_in_the_order_they_ran():
    res, _, _ = run("Setback 1.4 m. Height 3.2 m. Coverage 38%.", "trace-grant")
    spans = _exporter.get_finished_spans()
    steps = [s.attributes["adjudication.step"] for s in spans]
    assert res["decision"] == "GRANT"
    assert steps == ["intake", "guard_input", "retrieve", "guard_context", "assess",
                     "supervisor", "decide"]
    assert {s.attributes["adjudication.case_id"] for s in spans} == {"trace-grant"}
    assert spans[-2].attributes["adjudication.decision"] == "GRANT"


def test_waiting_for_an_officer_is_not_recorded_as_an_error():
    res, graph, cfg = run("Setback 0.6 m. Height 3.2 m. Coverage 38%.", "trace-refer")
    assert "__interrupt__" in res
    paused = _exporter.get_finished_spans()[-1]
    assert paused.attributes["adjudication.step"] == "escalate"
    assert paused.attributes["adjudication.paused_for_officer"] is True
    assert paused.status.status_code.name != "ERROR" and "error.type" not in paused.attributes

    graph.invoke(Command(resume=signed_reply(
        IDP, "idp-1", case_id="trace-refer", officer_id="off-9", decision="REFUSE",
        rationale="setback is below the minimum")), cfg)
    resumed = _exporter.get_finished_spans()[-1]
    assert resumed.attributes["adjudication.decision"] == "REFUSE"


def test_no_case_text_reaches_a_span():
    secret = "My neighbour Mr Alder at 16 Orchard Row objects."
    res, graph, cfg = run(f"Setback 0.6 m. Height 3.2 m. Coverage 38%. {secret}", "trace-text")
    graph.invoke(Command(resume=signed_reply(
        IDP, "idp-1", case_id="trace-text", officer_id="off-9", decision="REFUSE",
        rationale="confidential reasoning about Mr Alder")), cfg)
    recorded = json.dumps([[s.name, dict(s.attributes), [e.name for e in s.events]]
                           for s in _exporter.get_finished_spans()])
    for fragment in ("Alder", "Orchard", "Setback", "confidential"):
        assert fragment not in recorded
