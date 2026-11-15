# ADR-0016: Each step can be traced, and a trace never holds case text

**Status:** Accepted

## Context
The audit log answers why a case went where it did. It does not answer how long each step took or
where a slow case spent its time, and it is not something an operations team's tools can read.
Those tools read traces: timed records, called spans, in OpenTelemetry's format.

The people who can read a trace store are a wider group than the people who may read a case file.

## Decision
* Each node of the graph is wrapped so that running it opens one span, `adjudication.<step>`.
* A span carries the case id, the step name and, where the step produced one, the decision.
* A span never carries the applicant's narrative, retrieved text or an officer's rationale.
* A case pausing for an officer raises LangGraph's interrupt inside the step. That is recorded as
  `paused_for_officer`, not as an error. Any other exception sets `error.type`.
* The attribute names are this project's own. OpenTelemetry's names for AI agents are still marked
  as in development, and these steps are graph nodes, not model calls, so borrowing those names
  would claim more than is true.
* Tracing needs only the OpenTelemetry API package, as an optional extra. Without it the wrapper
  returns the step unchanged.

## Consequences
* Three tests with OpenTelemetry's in-memory exporter: a granted case yields its seven steps in
  order; a paused case is not an error and its resumed step carries the officer's decision; and a
  narrative naming a neighbour, with a rationale marked confidential, leaves no fragment in any
  span.
* The audit log is unchanged and remains the record. A trace can be sampled or dropped; the log
  cannot.

## Open questions
* The case id is on every span. If case ids are themselves sensitive, they need hashing.
