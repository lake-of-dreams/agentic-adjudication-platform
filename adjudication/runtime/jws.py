"""ES256 signing in the form JSON Web Signature (JWS, RFC 7515) expects.

Shared by the A2A agent card and the officer confirmation token. The
cryptography package signs and verifies in DER; JWS carries the raw 64-byte
r||s pair. Getting that conversion wrong in one place and right in another is
how two halves of a system stop agreeing on what a valid signature is.
"""
from __future__ import annotations

import base64

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import (
    decode_dss_signature,
    encode_dss_signature,
)


def b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def new_key() -> ec.EllipticCurvePrivateKey:
    return ec.generate_private_key(ec.SECP256R1())


def es256_sign(key: ec.EllipticCurvePrivateKey, signing_input: bytes) -> bytes:
    r, s = decode_dss_signature(key.sign(signing_input, ec.ECDSA(hashes.SHA256())))
    return r.to_bytes(32, "big") + s.to_bytes(32, "big")


def es256_verify(key: ec.EllipticCurvePublicKey, signing_input: bytes, raw: bytes) -> bool:
    if len(raw) != 64:
        return False
    der = encode_dss_signature(int.from_bytes(raw[:32], "big"), int.from_bytes(raw[32:], "big"))
    try:
        key.verify(der, signing_input, ec.ECDSA(hashes.SHA256()))
    except InvalidSignature:
        return False
    return True
