# ADR-0017: An officer's reply is signed, and the signature is checked before the reply is recorded

**Status:** Accepted

## Context
ADR-0014 made a paused case accept only a reply with the right shape: a named officer and one of
three decisions. It left one gap open. The reply named an officer and proved nothing. Whoever
could reach the resume call could type `off-9` and decide the case as that officer.

Issuing a permit already needs a token signed by the identity provider for that officer and that
exact call (ADR-0013). Deciding a referred case is as consequential, and for a refusal it is the
most consequential thing in the system.

The first attempt checked the signature inside the `escalate` node, after `interrupt()` returned.
The tests for forged replies passed. The test that sends a forged reply and then the genuine one
failed: the genuine reply was refused with "confirms a different call". LangGraph records a resume
value as soon as it passes the schema check. The forged reply had the right shape, so it was
recorded, and then the node refused it. From then on every resume of that case replayed the
recorded forged value and ignored the new one. One bad reply made the case impossible to decide.
Anyone who could reach the resume call could freeze any waiting case that way.

## Decision
* A reply carries a `confirmation`: a token of the same kind as ADR-0013, signed by the identity
  provider, for audience `adjudication-resume`, bound to the officer, the case id and the decision.
* The check is part of the reply's schema. `reply_model` in `adjudication/agents/officer.py` builds
  a Pydantic model for the case, and its validator verifies the token. A reply that fails is refused
  before LangGraph records it, so the case stays open to the next reply.
* Nothing after `interrupt()` in the node may refuse a reply. A comment at that line says why.
* The graph is given the identity provider's public keys. With none, no case can be resumed.
* The token is not marked as spent. A case is decided once: after that its graph has ended, and a
  second signed decision for it changes nothing. Marking tokens spent would add a way to get stuck
  if the process stopped between spending the token and finishing the step.
* The token lives five minutes, like any confirmation.

## Consequences
* Nine tests. A typed officer id, a token signed by an untrusted key, one officer's token under
  another's name, a signed "request information" changed to "grant", a token for another case, an
  expired token and a graph with no keys each decide nothing. A refused reply followed by the
  genuine one decides the case. A decided case cannot be decided again.
* The demo and every test that resumes a case now sign their replies, with a key that stands in
  for the identity provider.
* The finding about recorded replies applies to any node that pauses: validation that can refuse
  belongs in the schema given to `interrupt()`, never after it.

## Open questions
* The identity provider is still simulated. A real one must issue tokens of this type and show the
  officer the case and the decision being signed.
* The rationale is not bound by the signature. Someone who intercepted a reply could change the
  officer's stated reason but not the decision.
