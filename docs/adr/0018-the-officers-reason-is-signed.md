# ADR-0018: An officer's stated reason is covered by their signature

**Status:** Accepted

## Context
An officer's reply to a referred case is signed for that officer, that case and that decision
(ADR-0017). The reply also carries the officer's reason. The reason was outside the signature.

The reason is what an applicant reads in a refusal letter and what an appeal examines. Someone who
intercepted a reply between the officer and the case could not change REFUSE to GRANT, but could
replace "height exceeds the limit" with a reason the officer never gave. The record would then show
a genuine decision by a named officer for an invented reason.

## Decision
* The call a reply's confirmation approves is now the case id, the decision and the reason. A reply
  with no reason signs that absence.
* The token still carries only a hash of the call (ADR-0013). The reason's text is not copied into
  a token that passes through the agent's side and may be logged along the way.
* The check stays where ADR-0017 put it, in the reply's schema, so a reply with an altered reason
  is refused before LangGraph records it and the genuine reply still decides the case.

## Consequences
* Two tests. A reason changed after signing and a reason removed are both refused, and the genuine
  reply then decides the case. A reason added to a reply signed without one is refused.
* A token issued under the old rule no longer verifies. Tokens live five minutes, so nothing issued
  before the change is still in use.
* The officer's client must send the reason to the signer exactly as it will send it to the case,
  character for character. A client that trims or reformats it afterwards breaks its own reply.

## Open questions
* A decision does not require a reason. Whether a refusal must carry one is the council's rule to
  set, and it would be one line in the reply's schema.
