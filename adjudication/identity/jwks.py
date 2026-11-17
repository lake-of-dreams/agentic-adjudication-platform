"""Public keys fetched from a signer's published key set (JWKS, RFC 7517).

A fixed dictionary of trusted keys works until the signer changes its key.
Signers rotate keys on a schedule and after any suspected leak, and they
publish the current set at a URL. This follows that URL.

Three rules keep the fetch from becoming a weakness:

* The URL is given by whoever configures the service. It is never read from a
  token, or a forger would name their own key set.
* A key id the cache does not hold triggers one refetch, since that is what a
  rotation looks like. Refetches are spaced out, so a stream of tokens with
  made-up key ids cannot make this service hammer the signer.
* If the signer cannot be reached, the keys already held stay in use until
  they are too old, and then nothing is trusted: fail closed.
"""
from __future__ import annotations

import json
import threading
import time
import urllib.request
from collections.abc import Callable
from typing import Any

from cryptography.hazmat.primitives.asymmetric import ec, rsa

from adjudication.runtime.jws import b64, unb64

PublicKey = ec.EllipticCurvePublicKey | rsa.RSAPublicKey


def _int(text: str) -> int:
    return int.from_bytes(unb64(text), "big")


def key_from_jwk(jwk: dict[str, Any]) -> PublicKey | None:
    """One published key, or None for a kind this code does not use."""
    try:
        if jwk.get("use", "sig") != "sig":
            return None
        if jwk.get("kty") == "EC" and jwk.get("crv") == "P-256":
            return ec.EllipticCurvePublicNumbers(_int(jwk["x"]), _int(jwk["y"]),
                                                 ec.SECP256R1()).public_key()
        if jwk.get("kty") == "RSA":
            return rsa.RSAPublicNumbers(_int(jwk["e"]), _int(jwk["n"])).public_key()
    except (KeyError, ValueError, TypeError):
        return None
    return None


def jwk_from_ec_key(key: ec.EllipticCurvePublicKey, kid: str) -> dict[str, str]:
    n = key.public_numbers()
    return {"kty": "EC", "crv": "P-256", "use": "sig", "alg": "ES256", "kid": kid,
            "x": b64(n.x.to_bytes(32, "big")), "y": b64(n.y.to_bytes(32, "big"))}


def fetch_json(url: str, timeout: float = 5.0) -> Any:
    if not url.startswith(("https://", "http://localhost", "http://127.0.0.1")):
        # A key set fetched over plain HTTP can be swapped by anyone on the path.
        raise ValueError(f"refusing to fetch keys over plain HTTP from {url}")
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return json.loads(resp.read(1 << 20))


class JwksKeys:
    """Trusted keys by key id, kept in step with a published key set."""

    def __init__(self, url: str, *, kind: type | tuple[type, ...] = ec.EllipticCurvePublicKey,
                 min_refetch_s: float = 30.0, max_age_s: float = 24 * 3600.0,
                 fetch: Callable[[str], Any] = fetch_json,
                 clock: Callable[[], float] = time.monotonic):
        self._url, self._kind = url, kind
        self._min_refetch_s, self._max_age_s = min_refetch_s, max_age_s
        self._fetch, self._clock = fetch, clock
        self._lock = threading.Lock()
        self._keys: dict[str, PublicKey] = {}
        self._fetched: float | None = None      # last successful fetch
        self._tried: float | None = None        # last attempt, successful or not

    def _refresh(self) -> None:
        self._tried = self._clock()
        try:
            doc = self._fetch(self._url)
            keys = {j["kid"]: k for j in doc["keys"]
                    if isinstance(j, dict) and isinstance(j.get("kid"), str)
                    and isinstance(k := key_from_jwk(j), self._kind)}
        except Exception:  # unreachable, not JSON, wrong shape: keep what we hold
            return
        self._keys, self._fetched = keys, self._tried

    def get(self, kid: str, /) -> PublicKey | None:
        with self._lock:
            now = self._clock()
            too_old = self._fetched is None or now - self._fetched > self._max_age_s
            waited = self._tried is None or now - self._tried >= self._min_refetch_s
            if (too_old or kid not in self._keys) and waited:
                self._refresh()
            if self._fetched is None or now - self._fetched > self._max_age_s:
                return None
            return self._keys.get(kid)
