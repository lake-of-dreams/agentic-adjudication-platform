"""Optional tracing: one span per step a case takes through the graph.

Off unless OpenTelemetry's API is installed and the running process has
configured an exporter. Without the package, traced() returns the step
unchanged.

A span says which case, which step, how long it took and, where the step
produced one, the decision. It never holds the applicant's narrative, the
retrieved text or an officer's rationale: a trace store is read by more people
than a case file is. The audit log remains the record of why (ADR-0016).
"""
from __future__ import annotations

import functools
from collections.abc import Callable

try:
    from opentelemetry import trace
    from opentelemetry.trace import Status, StatusCode
except ImportError:  # tracing is an extra
    trace = None


def traced(step: str, fn: Callable) -> Callable:
    if trace is None:
        return fn

    @functools.wraps(fn)
    def run(state):
        tracer = trace.get_tracer("adjudication")
        with tracer.start_as_current_span(
                f"adjudication.{step}", record_exception=False, set_status_on_exception=False,
                attributes={"adjudication.case_id": state.get("case_id", ""),
                            "adjudication.step": step}) as span:
            try:
                out = fn(state)
            except Exception as exc:
                # GraphInterrupt is how a case pauses for an officer. Waiting is
                # not a failure, so it is named but not marked as an error.
                if type(exc).__name__ == "GraphInterrupt":
                    span.set_attribute("adjudication.paused_for_officer", True)
                else:
                    span.set_attribute("error.type", type(exc).__name__)
                    span.set_status(Status(StatusCode.ERROR, type(exc).__name__))
                raise
            if isinstance(out, dict) and out.get("decision"):
                span.set_attribute("adjudication.decision", out["decision"])
            return out
    return run
