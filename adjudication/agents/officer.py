"""An officer's decision on a referred case, signed so it cannot be typed by someone else.

A referred case resumes with a reply naming an officer and a decision. Checking
the reply's shape (ADR-0014) stopped nonsense decisions. It did not stop anyone
who can reach the resume call from typing another officer's id.

The reply now carries a confirmation: the same kind of token that guards
issue_permit (ADR-0013), signed by the identity provider after the officer
decides there. It is bound to the officer, to this case and to the decision, so
a token for REQUEST_INFORMATION on one case cannot GRANT another (ADR-0017).
It is bound to the officer's stated reason as well. The reason is what an
appeal reads, and a reply whose reason was changed on the way is refused like
one whose decision was (ADR-0018).

The signature is checked as part of validating the reply, not afterwards.
LangGraph records a resume value once it has passed validation. A reply that
passed the shape check and was then refused inside the node stayed recorded,
and every later reply to that case was ignored in its favour: one bad reply
and the case could never be decided.

`signed_reply` stands in for the approval service, for tests and the demo.
`adjudication.identity` holds the real one (ADR-0019).
"""
from __future__ import annotations

import time
from collections.abc import Callable
from typing import Annotated, Any, Literal

from cryptography.hazmat.primitives.asymmetric import ec
from pydantic import BaseModel, ConfigDict, StringConstraints, model_validator

from adjudication.mcp_server.confirmation import (
    KeySource,
    issue_confirmation,
    verify_confirmation,
)

RESUME_AUDIENCE = "adjudication-resume"
RESUME_TOOL = "resume_case"


def resume_call(case_id: str, decision: str, rationale: str | None) -> dict[str, Any]:
    """The exact call a reply's confirmation approves. The token carries only a
    hash of it, so the officer's reason is bound without being copied into a
    token that passes through the agent's side."""
    return {"case_id": case_id, "decision": decision, "rationale": rationale}


def signed_reply(key: ec.EllipticCurvePrivateKey, kid: str, *, case_id: str, officer_id: str,
                 decision: str, rationale: str | None = None, now: float | None = None) -> dict:
    """What the officer's client sends once the identity provider has signed the decision."""
    reply = {"officer_id": officer_id, "decision": decision,
             "confirmation": issue_confirmation(
                 key, kid, officer=officer_id, audience=RESUME_AUDIENCE, tool=RESUME_TOOL,
                 arguments=resume_call(case_id, decision, rationale),
                 now=time.time() if now is None else now)}
    if rationale is not None:
        reply["rationale"] = rationale
    return reply


def reply_model(case_id: str, trusted_keys: KeySource,
                wall_clock: Callable[[], float] = time.time) -> type[BaseModel]:
    """The shape of a valid reply to this case, including who must have signed it.

    Built per case because the signature is bound to the case id. With no
    trusted keys every reply is refused: fail closed.

    Single use is not checked here. A case is decided once: after that its
    graph has ended and there is nothing left to resume.
    """
    class OfficerReply(BaseModel):
        model_config = ConfigDict(extra="forbid")

        officer_id: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
        decision: Literal["GRANT", "REFUSE", "REQUEST_INFORMATION"]
        # Signed for this officer, case, decision and reason.
        confirmation: str
        rationale: str | None = None

        @model_validator(mode="after")
        def signed_by_this_officer_for_this_case(self):
            verify_confirmation(self.confirmation, trusted_keys=trusted_keys,
                                audience=RESUME_AUDIENCE, officer=self.officer_id, tool=RESUME_TOOL,
                                arguments=resume_call(case_id, self.decision, self.rationale),
                                now=wall_clock(), used=None)
            return self

    return OfficerReply
