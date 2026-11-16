# ADR-0014: An officer's reply is checked before it can decide a case

**Status:** Accepted

## Context
A referred case pauses at `interrupt()` and resumes with whatever the officer's client sends back.
The `escalate` node read that reply with `officer.get("decision")` and wrote it straight into the
case.

Sending the reply `{"decision": "APPROVE_EVERYTHING"}` to a paused case showed what that allowed.
The case's decision became `APPROVE_EVERYTHING`, and the audit log recorded that `officer:unknown`
had decided it. Nothing checked that the decision was one an officer can take, or that anyone was
named. Every other entry point in the system fails closed (ADR-0007). This one did not.

LangGraph 1.2.12 added a `response_schema` argument to `interrupt()`. Given a typed description of
the reply, it validates the resume value before the node sees it, and publishes the description to
the client as JSON Schema so a form can be drawn from it.

## Decision
* `OfficerReply` in `adjudication/agents/state.py` describes a reply: `officer_id`, a string;
  `decision`, one of `GRANT`, `REFUSE` or `REQUEST_INFORMATION`; and an optional `rationale`.
* `escalate` passes it as `response_schema`. A reply that does not match raises before any line
  after `interrupt()` runs.
* An `officer_id` that is empty or only spaces is refused by the node itself. The schema says
  "a string", and a blank string is one.
* `REFER_TO_OFFICER` is not an allowed reply. An officer cannot answer a referral by referring it.

## Consequences
* Eight tests. Six malformed replies each leave the audit log without a `decided` entry and the
  case still referred. One sends a malformed reply and then a good one to the same case, and checks
  the case is decided once and was suspended once. One reads the schema off the interrupt.
* A reply refused by the shape check does not consume the pause. The case can still be resumed
  with a valid one. ADR-0017 found that this is not true of a reply refused after the check.
* The minimum LangGraph version is now 1.2.22, the release this was run on.

## Open questions
* The reply names an officer; it does not prove one. Whoever can reach the resume call can type any
  officer's id. Issuing a permit already needs a signed confirmation (ADR-0013). Resuming a case
  should be bound to a verified identity the same way before this runs for real.
  **Closed by ADR-0017:** the reply carries a signed confirmation bound to the officer, the case
  and the decision.
