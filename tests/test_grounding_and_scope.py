"""Tests for fail-closed tool scope, quoted evidence,
rule bugs, and checkpoints that survive a restart.

Each test names the ADR that records the decision it protects.
"""
from __future__ import annotations

import datetime as dt

import pytest
from langgraph.types import Command

from adjudication.agents.graph import build_graph, durable_checkpointer
from adjudication.data.corpus import CORPUS
from adjudication.domain.criteria import check_heritage, check_setback, evaluate
from adjudication.runtime.audit import AuditLog
from adjudication.runtime.tools_registry import (
    ALL_CASES,
    Effect,
    Principal,
    Tool,
    ToolDenied,
    ToolRegistry,
)

NOW = dt.datetime(2026, 9, 14, 12, 0, tzinfo=dt.UTC)
CLEAN = "Setback 1.4 m. Height 3.2 m. Coverage 38%."


def _registry() -> ToolRegistry:
    r = ToolRegistry()
    r.register(Tool("read_case", Effect.READ, frozenset({"officer"}), lambda **_: "ok"))
    r.register(Tool("list_criteria", Effect.READ, frozenset({"officer"}), lambda: ["C1"],
                    case_scoped=False))
    return r


# ---------------------------------------------------------------- scope, ADR-0007
def test_empty_scope_means_no_cases():
    """An unset scope used to mean every case."""
    p = Principal("off-1", frozenset({"officer"}), Effect.READ)
    with pytest.raises(ToolDenied, match="not scoped"):
        _registry().invoke("read_case", p, Effect.READ, case_id="C1")


def test_case_scoped_tool_without_case_id_is_refused():
    p = Principal("off-1", frozenset({"officer"}), Effect.READ, frozenset({"C1"}))
    with pytest.raises(ToolDenied, match="no case_id"):
        _registry().invoke("read_case", p, Effect.READ)


def test_all_cases_is_an_explicit_grant():
    p = Principal("sup-1", frozenset({"officer"}), Effect.READ, ALL_CASES)
    assert _registry().invoke("read_case", p, Effect.READ, case_id="any") == "ok"


def test_tool_that_touches_no_case_needs_no_scope():
    p = Principal("off-1", frozenset({"officer"}), Effect.READ)
    assert _registry().invoke("list_criteria", p, Effect.READ) == ["C1"]


def test_denials_are_recorded():
    r = _registry()
    p = Principal("off-1", frozenset({"officer"}), Effect.READ)
    with pytest.raises(ToolDenied):
        r.invoke("read_case", p, Effect.READ, case_id="C9")
    assert r.invocations[-1] == ("read_case", "off-1", False, "argument scope")


# ---------------------------------------------------------------- evidence, ADR-0010
def test_measured_findings_quote_the_sentence_they_used():
    f = {x.criterion_code: x for x in evaluate(CLEAN)}
    assert f["C1"].evidence[0].quote == "Setback 1.4 m"
    assert f["C2"].evidence[0].quote == "Height 3.2 m"
    assert f["C3"].evidence[0].quote == "Coverage 38%"
    assert all(f[c].grounded for c in ("C1", "C2", "C3"))


def test_absence_is_grounded_by_the_search_not_by_a_quote():
    f = {x.criterion_code: x for x in evaluate(CLEAN)}
    assert f["C4"].evidence == [] and f["C4"].absence_checked and f["C4"].grounded


def test_every_quote_appears_verbatim_in_the_application():
    text = "Setback 2.0 m. Flood zone 3. Flood risk assessment attached. Listed building."
    for finding in evaluate(text):
        for e in finding.evidence:
            assert e.quote in text


def test_finding_with_no_quote_and_no_search_is_not_grounded():
    f = {x.criterion_code: x for x in evaluate("No numbers here.")}
    assert not f["C1"].grounded


# ---------------------------------------------------------------- rule bugs
def test_stated_zero_setback_is_read_not_skipped():
    """`a or b` treated 0 m as missing and fell through to the next keyword."""
    r = check_setback("Setback 0 m. Boundary wall 2.0 m high.")
    assert r.satisfied is False and "0.0 m" in r.rationale


@pytest.mark.parametrize("text,listed", [
    ("The house is Grade II listed.", True),
    ("A Grade II* building.", True),
    ("Grade I listed chapel.", True),
    ("grade | gravel path", False),
    ("Grade Information sheet attached.", False),
])
def test_heritage_grades_match_exactly(text, listed):
    """The old pattern was a character class, `grade [I|II]`."""
    r = check_heritage(text)
    assert (r.absence is False) == listed


def test_sentence_ending_in_a_number_is_split():
    """Regression, ADR-0005. 'zone 3. A' must be two sentences."""
    f = {x.criterion_code: x for x in evaluate("Site is in flood zone 3. A flood risk assessment is attached.")}
    assert f["C4"].satisfied is True
    assert f["C4"].evidence[0].quote == "A flood risk assessment is attached"


# ---------------------------------------------------------------- grant needs grounding
def test_clean_case_is_granted_with_grounded_findings():
    graph = build_graph(CORPUS, AuditLog(), now=NOW)
    out = graph.invoke({"case_id": "g-1", "narrative": CLEAN, "risk_tier": "STANDARD",
                        "trace": [], "guard_events": []},
                       {"configurable": {"thread_id": "g-1"}})
    assert out["decision"] == "GRANT"
    assert all(f["grounded"] for f in out["findings"])


# ---------------------------------------------------------------- durable resume, ADR-0009
def test_case_resumes_in_a_new_graph_from_sqlite(tmp_path):
    """A process that suspended for an officer can exit; a new one picks the case up."""
    db = str(tmp_path / "checkpoints.sqlite")
    cfg = {"configurable": {"thread_id": "durable-1"}}
    first = build_graph(CORPUS, AuditLog(), now=NOW, checkpointer=durable_checkpointer(db))
    res = first.invoke({"case_id": "durable-1", "narrative": "Setback 0.6 m. Height 5.1 m. Coverage 62%.",
                        "risk_tier": "STANDARD", "trace": [], "guard_events": []}, cfg)
    assert "__interrupt__" in res
    del first

    audit = AuditLog()
    second = build_graph(CORPUS, audit, now=NOW, checkpointer=durable_checkpointer(db))
    out = second.invoke(Command(resume={"officer_id": "off-3", "decision": "GRANT",
                                        "rationale": "revised plans"}), cfg)
    assert out["officer_decision"] == "GRANT"
    assert out["case_id"] == "durable-1"
    assert any(e.actor == "officer:off-3" for e in audit.for_case("durable-1"))
