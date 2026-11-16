"""An officer's decision on a referred case, signed so it cannot be typed by someone else.

A referred case resumes with a reply naming an officer and a decision. Checking
the reply's shape (ADR-0014) stopped nonsense decisions. It did not stop anyone
who can reach the resume call from typing another officer's id.

The reply now carries a confirmation: the same kind of token that guards
issue_permit (ADR-0013), signed by the identity provider after the officer
decides there. It is bound to the officer, to this case and to the decision, so
a token for REQUEST_INFORMATION on one case cannot GRANT another (ADR-0017).

The signature is checked as part of validating the reply, not afterwards.
LangGraph records a resume value once it has passed validation. A reply that
passed the shape check and was then refused inside the node stayed recorded,
and every later reply to that case was ignored in its favour: one bad reply
and the case could never be decided.

`signed_reply` stands in for the identity provider, for tests and the demo.
"""
from __future__ import annotations

import time
from collections.abc import Callable
from typing import Annotated, Any, Literal

from cryptography.hazmat.primitives.asymmetric import ec
from pydantic import BaseModel, ConfigDict, StringConstraints, model_validator

from adjudication.mcp_server.confirmation import issue_confirmation, verify_confirmation

RESUME_AUDIENCE = "adjudication-resume"
RESUME_TOOL = "resume_case"


def _call(case_id: str, decision: str) -> dict[str, Any]:
    return {"case_id": case_id, "decision": decision}


def signed_reply(key: ec.EllipticCurvePrivateKey, kid: str, *, case_id: str, officer_id: str,
                 decision: str, rationale: str | None = None, now: float | None = None) -> dict:
    """What the officer's client sends once the identity provider has signed the decision."""
    reply = {"officer_id": officer_id, "decision": decision,
             "confirmation": issue_confirmation(
                 key, kid, officer=officer_id, audience=RESUME_AUDIENCE, tool=RESUME_TOOL,
                 arguments=_call(case_id, decision), now=time.time() if now is None else now)}
    if rationale is not None:
        reply["rationale"] = rationale
    return reply


def reply_model(case_id: str, trusted_keys: dict[str, ec.EllipticCurvePublicKey],
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
        # Signed by the identity provider for this officer, case and decision.
        confirmation: str
        rationale: str | None = None

        @model_validator(mode="after")
        def signed_by_this_officer_for_this_case(self):
            verify_confirmation(self.confirmation, trusted_keys=trusted_keys,
                                audience=RESUME_AUDIENCE, officer=self.officer_id, tool=RESUME_TOOL,
                                arguments=_call(case_id, self.decision), now=wall_clock(), used=None)
            return self

    return OfficerReply
