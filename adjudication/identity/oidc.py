"""Checking who an officer is, from a token their sign-in service issued.

OpenID Connect (OIDC) is the standard most sign-in services speak. After an
officer signs in, the service gives their browser or command-line client an
access token: a signed statement of who they are, which roles they hold, who
the token is for and when it expires. This module checks one.

The sign-in service publishes a discovery document at
`<issuer>/.well-known/openid-configuration`, which says where its public keys
are. Nothing else is read from the network, and nothing is read from the token
until its signature has been checked.
"""
from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa

from adjudication.identity.jwks import JwksKeys, fetch_json
from adjudication.runtime.jws import es256_verify, unb64

CLOCK_SKEW_S = 30


class SignInRejected(Exception):
    """The access token does not prove who the caller is. `reason` says why."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class Officer:
    officer_id: str
    roles: frozenset[str]


@dataclass
class OidcVerifier:
    """Verifies access tokens from one issuer, for one audience."""

    issuer: str
    audience: str
    keys: JwksKeys
    # The claim that names the officer. Keycloak's `preferred_username` is the
    # sign-in name; `sub` is an opaque id that an audit log cannot be read by.
    id_claim: str = "preferred_username"

    @classmethod
    def discover(cls, issuer: str, audience: str, *, id_claim: str = "preferred_username",
                 fetch: Callable[[str], Any] = fetch_json) -> OidcVerifier:
        issuer = issuer.rstrip("/")
        doc = fetch(issuer + "/.well-known/openid-configuration")
        # The document must describe the issuer it was fetched from. Otherwise a
        # misconfigured address would quietly trust someone else's keys.
        if doc.get("issuer", "").rstrip("/") != issuer:
            raise ValueError(f"discovery document is for {doc.get('issuer')!r}, not {issuer!r}")
        keys = JwksKeys(doc["jwks_uri"], kind=(rsa.RSAPublicKey, ec.EllipticCurvePublicKey),
                        fetch=fetch)
        return cls(issuer=issuer, audience=audience, keys=keys, id_claim=id_claim)

    def verify(self, token: str, *, now: float) -> Officer:
        try:
            protected, payload, signature = token.split(".")
            header = json.loads(unb64(protected))
            raw = unb64(signature)
        except (AttributeError, ValueError):
            raise SignInRejected("malformed") from None
        if not isinstance(header, dict) or not isinstance(header.get("kid"), str):
            raise SignInRejected("malformed")

        key = self.keys.get(header["kid"])
        if key is None:
            raise SignInRejected("signed by a key the sign-in service does not publish")
        signed = f"{protected}.{payload}".encode()
        # The algorithm follows from the kind of key the issuer published, and
        # the header must agree. A header alone never chooses it: that is how
        # "alg": "none" and an HMAC keyed with the public key get accepted.
        alg = header.get("alg")
        if isinstance(key, rsa.RSAPublicKey) and alg == "RS256":
            try:
                key.verify(raw, signed, padding.PKCS1v15(), hashes.SHA256())
            except InvalidSignature:
                raise SignInRejected("bad signature") from None
        elif isinstance(key, ec.EllipticCurvePublicKey) and alg == "ES256":
            if not es256_verify(key, signed, raw):
                raise SignInRejected("bad signature")
        else:
            raise SignInRejected("wrong algorithm for the published key")

        try:
            claims = json.loads(unb64(payload))
        except ValueError:
            raise SignInRejected("malformed") from None
        if not isinstance(claims, dict):
            raise SignInRejected("malformed")
        if str(claims.get("iss", "")).rstrip("/") != self.issuer:
            raise SignInRejected("issued by another sign-in service")
        aud = claims.get("aud")
        if self.audience not in (aud if isinstance(aud, list) else [aud]):
            raise SignInRejected("issued for another service")
        exp = claims.get("exp")
        if not isinstance(exp, int | float) or exp <= now - CLOCK_SKEW_S:
            raise SignInRejected("expired")
        nbf = claims.get("nbf", claims.get("iat", 0))
        if isinstance(nbf, int | float) and nbf > now + CLOCK_SKEW_S:
            raise SignInRejected("not valid yet")
        # An ID token says the person signed in; it is addressed to the client
        # that asked, not to an API. Keycloak marks its types, so refuse one.
        if claims.get("typ") == "ID":
            raise SignInRejected("an ID token is not an access token")
        who = claims.get(self.id_claim)
        if not isinstance(who, str) or not who:
            raise SignInRejected("names nobody")
        realm = claims.get("realm_access")
        roles = realm.get("roles") if isinstance(realm, dict) else None
        return Officer(officer_id=who,
                       roles=frozenset(r for r in roles or [] if isinstance(r, str)))
