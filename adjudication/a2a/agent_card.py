"""A2A v1.0 agent card, signed.

JWS (RFC 7515) over JCS canonicalisation (RFC 8785). Two encodings of the same
object have to come out as identical bytes, otherwise verification fails in ways
that look random.

HMAC stands in for real keys here. Swap sign_card/verify_card for RS256 against
a JWKS endpoint before this faces anything real.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
from typing import Any

CARD: dict[str, Any] = {
    "protocolVersion": "1.0",
    "name": "adjudication-agent",
    "description": "Assesses permit applications against published criteria. "
                   "Recommends grant; never issues a refusal.",
    "url": "https://adjudication.example.org/a2a",
    "version": "1.0.0",
    "capabilities": {"streaming": False, "pushNotifications": False},
    "defaultInputModes": ["text/plain"],
    "defaultOutputModes": ["application/json"],
    "skills": [
        {"id": "assess_application", "name": "Assess application",
         "description": "Evaluate an application against criteria C1-C5.",
         "tags": ["adjudication", "regulated"]},
        {"id": "explain_decision", "name": "Explain decision",
         "description": "Reconstruct the decision path for a case from the audit log.",
         "tags": ["audit", "explainability"]},
    ],
    # callers can check this rather than take it on trust: the agent cannot refuse
    "x-authority": {"mayRecommendGrant": True, "mayIssueRefusal": False,
                    "escalatesTo": "human-officer"},
}


def jcs_canonicalise(obj: Any) -> bytes:
    """RFC 8785-style: sorted keys, no insignificant space, UTF-8. Good enough for
    the object shapes an agent card uses; not a full implementation."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def sign_card(card: dict, key: bytes, kid: str = "key-1") -> dict:
    header = {"alg": "HS256", "kid": kid, "typ": "a2a-card+jws"}
    h = _b64(jcs_canonicalise(header))
    p = _b64(jcs_canonicalise(card))
    sig = hmac.new(key, f"{h}.{p}".encode(), hashlib.sha256).digest()
    return {**card, "signatures": [{"protected": h, "signature": _b64(sig)}]}


def verify_card(signed: dict, key: bytes) -> bool:
    signed = dict(signed)
    sigs = signed.pop("signatures", None)
    if not sigs:
        return False
    entry = sigs[0]
    expected = hmac.new(
        key, f"{entry['protected']}.{_b64(jcs_canonicalise(signed))}".encode(),
        hashlib.sha256).digest()
    return hmac.compare_digest(_b64(expected), entry["signature"])
