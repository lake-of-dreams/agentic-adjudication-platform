"""Officer confirmations that the client cannot forge (ADR-0013).

An irreversible tool runs only after the officer the agent acts for confirms
it. The first version took the confirmation as a field the client sent back:
`{"confirmed": true, "confirmedBy": "off-7"}`. The client is the agent's side
of the connection, so the agent could write that field itself.

A confirmation is now a token signed by the identity provider after the
officer approves the action there. The client carries it but cannot make one.
The token says who confirmed, which server it is for, which exact call it
approves, and when it stops being valid. The server checks all of that against
the call in front of it, then records the token's id so it cannot be used again.

The call is identified by a hash of the tool name and its arguments in RFC 8785
canonical form. A token for `issue_permit` on case C1 does not approve
`issue_permit` on case C2, or the same tool with any argument changed.

`issue_confirmation` stands in for the identity provider, so the tests and the
demo can produce tokens. A real deployment never holds that private key here.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import uuid
from typing import Any

import rfc8785
from cryptography.hazmat.primitives.asymmetric import ec

from adjudication.runtime.jws import b64, es256_sign, es256_verify, unb64

TOKEN_TYPE = "adjudication-confirmation+jwt"
# An officer approves a specific action they are looking at, then it runs. Five
# minutes covers that; a token valid for a day is a standing permission.
MAX_LIFETIME_S = 300
# clocks on two machines disagree a little
CLOCK_SKEW_S = 30


class ConfirmationRejected(Exception):
    """The token does not confirm this call. `reason` says which check failed."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def call_digest(tool: str, arguments: dict[str, Any]) -> str:
    return b64(hashlib.sha256(rfc8785.dumps({"tool": tool, "arguments": arguments})).digest())


def issue_confirmation(key: ec.EllipticCurvePrivateKey, kid: str, *, officer: str, audience: str,
                       tool: str, arguments: dict[str, Any], now: float,
                       lifetime_s: int = MAX_LIFETIME_S, jti: str | None = None) -> str:
    """What the identity provider does once the officer has approved the action."""
    header = {"alg": "ES256", "typ": TOKEN_TYPE, "kid": kid}
    claims = {"sub": officer, "aud": audience, "iat": int(now), "exp": int(now) + lifetime_s,
              "jti": jti or uuid.uuid4().hex, "call": call_digest(tool, arguments)}
    signing_input = (b64(json.dumps(header, separators=(",", ":")).encode()) + "."
                     + b64(json.dumps(claims, separators=(",", ":")).encode()))
    return signing_input + "." + b64(es256_sign(key, signing_input.encode()))


class UsedConfirmations:
    """Token ids already spent, kept in SQLite so a restart does not forget them.

    An in-memory set lost every spent id on restart, which reopened a window to
    replay any token that had not yet expired. Ids are kept until the token
    would have expired anyway, plus the clock skew.
    """

    def __init__(self, path: str = ":memory:"):
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._lock = threading.Lock()
        with self._lock, self._db:
            self._db.execute("CREATE TABLE IF NOT EXISTS used_confirmation "
                             "(jti TEXT PRIMARY KEY, expires REAL NOT NULL)")

    def claim(self, jti: str, expires: float, now: float) -> bool:
        """True the first time an id is claimed, False on every later attempt."""
        with self._lock, self._db:
            self._db.execute("DELETE FROM used_confirmation WHERE expires < ?",
                             (now - CLOCK_SKEW_S,))
            try:
                self._db.execute("INSERT INTO used_confirmation VALUES (?, ?)", (jti, expires))
            except sqlite3.IntegrityError:
                return False
        return True


def verify_confirmation(token: str, *, trusted_keys: dict[str, ec.EllipticCurvePublicKey],
                        audience: str, officer: str, tool: str, arguments: dict[str, Any],
                        now: float, used: UsedConfirmations) -> dict:
    """Returns the claims when the token confirms exactly this call, else raises.

    The id is claimed last. A token that fails any other check stays unspent,
    so a client that sent it to the wrong call can still send it to the right one.
    """
    try:
        protected, payload, signature = token.split(".")
        header = json.loads(unb64(protected))
        claims = json.loads(unb64(payload))
        raw = unb64(signature)
    except (AttributeError, ValueError):
        raise ConfirmationRejected("malformed") from None
    if not isinstance(header, dict) or not isinstance(claims, dict):
        raise ConfirmationRejected("malformed")

    # Fixed algorithm. Reading it from the header is how "alg": "none" and
    # HMAC-with-the-public-key tokens get accepted elsewhere.
    if header.get("alg") != "ES256" or header.get("typ") != TOKEN_TYPE:
        raise ConfirmationRejected("wrong algorithm or token type")
    key = trusted_keys.get(header.get("kid"))
    if key is None:
        raise ConfirmationRejected("signed by a key this server does not trust")
    if not es256_verify(key, f"{protected}.{payload}".encode(), raw):
        raise ConfirmationRejected("bad signature")

    if claims.get("aud") != audience:
        raise ConfirmationRejected("issued for another server")
    iat, exp = claims.get("iat"), claims.get("exp")
    if not isinstance(iat, int) or not isinstance(exp, int):
        raise ConfirmationRejected("malformed")
    if exp - iat > MAX_LIFETIME_S:
        raise ConfirmationRejected("valid for longer than a confirmation may be")
    if iat > now + CLOCK_SKEW_S:
        raise ConfirmationRejected("issued in the future")
    if exp <= now - CLOCK_SKEW_S:
        raise ConfirmationRejected("expired")
    if claims.get("sub") != officer:
        raise ConfirmationRejected("confirmed by someone else")
    if claims.get("call") != call_digest(tool, arguments):
        raise ConfirmationRejected("confirms a different call")
    jti = claims.get("jti")
    if not isinstance(jti, str) or not jti:
        raise ConfirmationRejected("malformed")
    if not used.claim(jti, exp, now):
        raise ConfirmationRejected("already used")
    return claims
