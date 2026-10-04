"""A2A 1.0 agent card, signed.

An agent card is the document an agent publishes so other agents can find out
what it does and how to reach it. A2A 1.0 lists the agent's endpoints under
`supportedInterfaces`, each with its own protocol version, and signs the card
with a JSON Web Signature (JWS, RFC 7515) over the card's JSON Canonicalization
Scheme form (JCS, RFC 8785). Two encodings of the same object have to come out as
identical bytes, otherwise verification fails in ways that look random.

Signatures use ES256: an elliptic-curve key pair, so anyone holding the public
key can verify a card and only the holder of the private key can sign one. The
previous version used a shared HMAC secret, which lets every verifier forge
cards too (ADR-0012).

The rule that this agent never issues a refusal is published as a declared
extension, the place A2A 1.0 gives agents for anything beyond the core fields.
"""
from __future__ import annotations

import base64
import copy
import json
from typing import Any

import rfc8785
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import (
    decode_dss_signature,
    encode_dss_signature,
)

AUTHORITY_EXTENSION = "https://adjudication.example.org/a2a/extensions/authority/v1"

CARD: dict[str, Any] = {
    "name": "adjudication-agent",
    "description": "Assesses permit applications against published criteria. "
                   "Recommends grant; never issues a refusal.",
    "supportedInterfaces": [
        {"url": "https://adjudication.example.org/a2a/v1",
         "protocolBinding": "JSONRPC", "protocolVersion": "1.0"},
    ],
    "version": "1.1.0",
    "capabilities": {
        "streaming": False,
        "pushNotifications": False,
        # callers can check this rather than take it on trust: the agent cannot refuse
        "extensions": [{
            "uri": AUTHORITY_EXTENSION,
            "description": "Limits on what this agent may decide on its own.",
            "required": False,
            "params": {"mayRecommendGrant": True, "mayIssueRefusal": False,
                       "escalatesTo": "human-officer"},
        }],
    },
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
}


def jcs_canonicalise(obj: Any) -> bytes:
    """RFC 8785 canonical form, from the rfc8785 package rather than a hand-rolled
    json.dumps, which differs from RFC 8785 on number formatting."""
    return rfc8785.dumps(obj)


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def new_signing_key() -> ec.EllipticCurvePrivateKey:
    return ec.generate_private_key(ec.SECP256R1())


def sign_card(card: dict, key: ec.EllipticCurvePrivateKey, kid: str = "key-1",
              jku: str | None = None) -> dict:
    """Adds an ES256 signature. The signatures field is never part of what is signed."""
    # A deep copy, so a caller editing the signed card cannot change the original.
    unsigned = copy.deepcopy({k: v for k, v in card.items() if k != "signatures"})
    header = {"alg": "ES256", "typ": "JOSE", "kid": kid}
    if jku:
        header["jku"] = jku
    protected = _b64(json.dumps(header, separators=(",", ":")).encode())
    signing_input = f"{protected}.{_b64(jcs_canonicalise(unsigned))}".encode()
    der = key.sign(signing_input, ec.ECDSA(hashes.SHA256()))
    # JWS ES256 wants the raw 64-byte r||s form, not the DER that cryptography returns.
    r, s = decode_dss_signature(der)
    raw = r.to_bytes(32, "big") + s.to_bytes(32, "big")
    existing = list(card.get("signatures", []))
    return {**unsigned, "signatures": [*existing, {"protected": protected, "signature": _b64(raw)}]}


def verify_card(signed: dict, public_keys: dict[str, ec.EllipticCurvePublicKey]) -> bool:
    """True when at least one signature verifies against a trusted key.

    `public_keys` maps key ids to keys the caller already trusts. A signature
    naming an unknown key, or an algorithm other than ES256, does not count.
    """
    sigs = signed.get("signatures") or []
    unsigned = {k: v for k, v in signed.items() if k != "signatures"}
    payload = _b64(jcs_canonicalise(unsigned))
    for entry in sigs:
        try:
            header = json.loads(_unb64(entry["protected"]))
            key = public_keys.get(header.get("kid"))
            if key is None or header.get("alg") != "ES256":
                continue
            raw = _unb64(entry["signature"])
            if len(raw) != 64:
                continue
            der = encode_dss_signature(int.from_bytes(raw[:32], "big"),
                                       int.from_bytes(raw[32:], "big"))
            key.verify(der, f"{entry['protected']}.{payload}".encode(),
                       ec.ECDSA(hashes.SHA256()))
            return True
        except (InvalidSignature, KeyError, ValueError, TypeError):
            continue
    return False
