"""The sign-in check, the published keys and the approval service (ADR-0019).

The sign-in service here is a local web server holding an RSA key, publishing
the same two documents a real one does. `make idp-check` runs the same path
against Keycloak.
"""
import datetime as dt
import json
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from cryptography.hazmat.primitives import hashes, hmac
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from langgraph.types import Command

from adjudication.agents.graph import build_graph
from adjudication.agents.officer import RESUME_AUDIENCE, RESUME_TOOL, resume_call
from adjudication.data.corpus import CORPUS
from adjudication.identity.approval import ApprovalService, serve
from adjudication.identity.jwks import JwksKeys, fetch_json, jwk_from_ec_key
from adjudication.identity.oidc import OidcVerifier, SignInRejected
from adjudication.runtime.audit import AuditLog
from adjudication.runtime.jws import b64, new_key

T = 1_800_000_000  # wall-clock "now" for every token in this file
AUD = "adjudication-approval"
NOW = dt.datetime(2026, 9, 14, 12, 0, tzinfo=dt.UTC)
REFERRED = "Setback 0.6 m. Height 5.1 m. Coverage 62%."


def _part(obj: dict) -> str:
    return b64(json.dumps(obj, separators=(",", ":")).encode())


class SignIn:
    """A sign-in service: one RSA key, a discovery document and a key set."""

    def __init__(self):
        self.key, self.kid = rsa.generate_private_key(65537, 2048), "rsa-1"
        self.fetches = 0
        outer = self

        class H(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path == "/realms/council/.well-known/openid-configuration":
                    body = {"issuer": outer.issuer, "jwks_uri": outer.issuer + "/certs"}
                elif self.path == "/realms/council/certs":
                    outer.fetches += 1
                    body = outer.jwks()
                else:
                    self.send_response(404)
                    self.end_headers()
                    return
                raw = json.dumps(body).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def log_message(self, *_):
                pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.issuer = f"http://127.0.0.1:{self.httpd.server_address[1]}/realms/council"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def jwks(self) -> dict:
        n = self.key.public_key().public_numbers()
        return {"keys": [{"kty": "RSA", "use": "sig", "alg": "RS256", "kid": self.kid,
                          "n": b64(n.n.to_bytes((n.n.bit_length() + 7) // 8, "big")),
                          "e": b64(n.e.to_bytes(3, "big"))}]}

    def rotate(self) -> None:
        self.key, self.kid = rsa.generate_private_key(65537, 2048), "rsa-2"

    def token(self, who="off-014", roles=("officer",), **over) -> str:
        claims = {"iss": self.issuer, "aud": [AUD, "account"], "exp": T + 300, "iat": T,
                  "typ": "Bearer", "sub": "3f2c-opaque", "preferred_username": who,
                  "realm_access": {"roles": list(roles)}} | over
        signing_input = _part({"alg": "RS256", "typ": "JWT", "kid": self.kid}) + "." + _part(claims)
        sig = self.key.sign(signing_input.encode(), padding.PKCS1v15(), hashes.SHA256())
        return signing_input + "." + b64(sig)


@pytest.fixture(scope="module")
def signin():
    s = SignIn()
    yield s
    s.httpd.shutdown()


@pytest.fixture
def verifier(signin):
    return OidcVerifier.discover(signin.issuer, AUD)


# ------------------------------------------------------------ the sign-in check
def test_a_signed_in_officer_is_recognised_with_their_roles(signin, verifier):
    officer = verifier.verify(signin.token(), now=T)
    assert officer.officer_id == "off-014" and "officer" in officer.roles


@pytest.mark.parametrize(("change", "why"), [
    ({"iss": "https://elsewhere.example/realms/council"}, "another sign-in service"),
    ({"aud": "some-other-api"}, "another service"),
    ({"exp": T - 3600}, "expired"),
    ({"iat": T + 3600, "exp": T + 3900}, "not valid yet"),
    ({"typ": "ID"}, "ID token"),
    ({"preferred_username": ""}, "names nobody"),
])
def test_a_token_that_is_not_for_here_and_now_is_refused(signin, verifier, change, why):
    with pytest.raises(SignInRejected, match=why):
        verifier.verify(signin.token(**change), now=T)


def test_a_token_with_no_signature_algorithm_is_refused(signin, verifier):
    head, body, _ = signin.token().split(".")
    unsigned = _part({"alg": "none", "typ": "JWT", "kid": signin.kid}) + "." + body + "."
    with pytest.raises(SignInRejected, match="wrong algorithm"):
        verifier.verify(unsigned, now=T)


def test_a_token_keyed_with_the_public_key_is_refused(signin, verifier):
    """The classic confusion: the verifier is told HS256 and uses the public
    key, which everyone has, as the shared secret."""
    _, body, _ = signin.token(roles=("officer", "admin")).split(".")
    signing_input = _part({"alg": "HS256", "typ": "JWT", "kid": signin.kid}) + "." + body
    pem = signin.key.public_key().public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo)
    mac = hmac.HMAC(pem, hashes.SHA256())
    mac.update(signing_input.encode())
    with pytest.raises(SignInRejected, match="wrong algorithm"):
        verifier.verify(signing_input + "." + b64(mac.finalize()), now=T)


def test_a_token_from_someone_elses_key_is_refused(signin, verifier):
    other = SignIn()
    other.issuer, other.kid = signin.issuer, signin.kid   # claims to be the real service
    with pytest.raises(SignInRejected, match="bad signature"):
        verifier.verify(other.token(), now=T)
    other.httpd.shutdown()


def test_discovery_refuses_a_document_that_describes_another_issuer(signin):
    def lying(_url):
        return {"issuer": "https://elsewhere.example", "jwks_uri": signin.issuer + "/certs"}
    with pytest.raises(ValueError, match="not"):
        OidcVerifier.discover(signin.issuer, AUD, fetch=lying)


# ------------------------------------------------------------ published keys
def test_keys_are_never_fetched_over_plain_http_from_another_machine():
    with pytest.raises(ValueError, match="plain HTTP"):
        fetch_json("http://idp.council.example/certs")


def _keyset(*kids):
    made = {k: new_key() for k in kids}
    return made, {"keys": [jwk_from_ec_key(v.public_key(), k) for k, v in made.items()]}


def test_a_rotated_key_is_found_and_made_up_key_ids_do_not_cause_a_fetch_each():
    now, calls, published = [0.0], [], [_keyset("k1")[1]]
    keys = JwksKeys("https://signer/jwks", min_refetch_s=30, clock=lambda: now[0],
                    fetch=lambda url: calls.append(url) or published[0])
    assert keys.get("k1") is not None and len(calls) == 1
    for i in range(50):                       # a stream of forged tokens
        assert keys.get(f"made-up-{i}") is None
    assert len(calls) == 1
    published[0] = _keyset("k2")[1]           # the signer rotates
    now[0] = 31.0
    assert keys.get("k2") is not None and len(calls) == 2
    assert keys.get("k1") is None             # the retired key is no longer trusted


def test_an_unreachable_signer_keeps_known_keys_for_a_while_then_trusts_nothing():
    now, up = [0.0], [True]
    doc = _keyset("k1")[1]

    def fetch(_url):
        if not up[0]:
            raise OSError("connection refused")
        return doc
    keys = JwksKeys("https://signer/jwks", min_refetch_s=30, max_age_s=3600,
                    clock=lambda: now[0], fetch=fetch)
    assert keys.get("k1") is not None
    up[0] = False
    now[0] = 1800.0
    assert keys.get("k1") is not None         # an outage is not a reason to stop work at once
    now[0] = 3700.0
    assert keys.get("k1") is None             # but stale keys are not trusted for ever


def test_a_signer_that_was_never_reachable_trusts_nothing():
    def down(_url):
        raise OSError("connection refused")
    assert JwksKeys("https://signer/jwks", fetch=down).get("k1") is None


# ------------------------------------------------------------ the approval service
@pytest.fixture
def approval(verifier):
    service = ApprovalService(verifier, audiences=frozenset({RESUME_AUDIENCE}),
                              wall_clock=lambda: T)
    httpd = serve(service, port=0)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield service, f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


def _ask(url: str, token: str | None, body: dict) -> tuple[int, dict]:
    req = urllib.request.Request(url + "/confirmations", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def _decision(case_id: str, decision: str, rationale: str | None = None) -> dict:
    return {"audience": RESUME_AUDIENCE, "tool": RESUME_TOOL,
            "arguments": resume_call(case_id, decision, rationale)}


def _paused(case_id: str, keys):
    audit = AuditLog()
    graph = build_graph(CORPUS, audit, now=NOW, officer_keys=keys, wall_clock=lambda: T)
    cfg = {"configurable": {"thread_id": case_id}}
    res = graph.invoke({"case_id": case_id, "narrative": REFERRED, "risk_tier": "STANDARD",
                        "trace": [], "guard_events": []}, cfg)
    assert "__interrupt__" in res
    return audit, graph, cfg


def test_an_officer_signs_in_approves_and_the_case_resumes_on_published_keys(signin, approval):
    """The whole path with nothing shared by hand: the graph learns the approval
    service's key from the URL it publishes, as a separate process would."""
    _, url = approval
    audit, graph, cfg = _paused("idp-1", JwksKeys(url + "/.well-known/jwks.json"))
    status, body = _ask(url, signin.token(who="off-014"),
                        _decision("idp-1", "REFUSE", "height exceeds the limit"))
    assert status == 200 and body["officer_id"] == "off-014"

    out = graph.invoke(Command(resume={"officer_id": "off-014", "decision": "REFUSE",
                                       "rationale": "height exceeds the limit",
                                       "confirmation": body["confirmation"]}), cfg)
    assert out["decision"] == "REFUSE"
    assert [e.actor for e in audit.for_case("idp-1")][-1] == "officer:off-014"


def test_the_confirmation_names_whoever_signed_in_and_nobody_else(signin, approval):
    _, url = approval
    audit, graph, cfg = _paused("idp-2", JwksKeys(url + "/.well-known/jwks.json"))
    _, body = _ask(url, signin.token(who="off-008"), _decision("idp-2", "GRANT"))
    with pytest.raises(Exception, match="someone else"):
        graph.invoke(Command(resume={"officer_id": "off-014", "decision": "GRANT",
                                     "confirmation": body["confirmation"]}), cfg)
    assert "decided" not in [e.action for e in audit.for_case("idp-2")]


@pytest.mark.parametrize(("token_kw", "status", "why"), [
    (None, 401, "sign in first"),
    ({"roles": ("clerk",)}, 403, "not as an officer"),
    ({"exp": T - 3600}, 401, "expired"),
    ({"aud": "some-other-api"}, 401, "another service"),
])
def test_nobody_but_a_signed_in_officer_gets_a_confirmation(signin, approval, token_kw, status, why):
    _, url = approval
    token = None if token_kw is None else signin.token(**token_kw)
    got, body = _ask(url, token, _decision("idp-3", "GRANT"))
    assert got == status and why in body["error"] and "confirmation" not in body


def test_a_confirmation_is_never_signed_for_a_server_it_does_not_know(signin, approval):
    _, url = approval
    status, body = _ask(url, signin.token(), _decision("idp-4", "GRANT") | {"audience": "payroll"})
    assert status == 400 and "confirmation" not in body


def test_the_sign_in_services_key_rotation_is_followed(approval):
    """Runs last in the module: it changes the shared sign-in service's key."""
    service, _ = approval
    signin = SignIn()
    service.verifier = OidcVerifier.discover(signin.issuer, AUD)
    service.verifier.keys._min_refetch_s = 0
    assert service.confirm(signin.token(), **_decision("idp-5", "GRANT"))[0] == "off-014"
    signin.rotate()
    assert service.confirm(signin.token(), **_decision("idp-5", "GRANT"))[0] == "off-014"
    assert signin.fetches == 2
    signin.httpd.shutdown()
