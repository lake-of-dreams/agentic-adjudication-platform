"""Signed officer confirmations for irreversible tools (ADR-0013).

Each test hands the server a token that is wrong in exactly one way and checks
the permit is not issued. The two tests at the top show a good token working,
so a failure further down cannot be blamed on a token that never verified.
"""
from __future__ import annotations

import base64
import json

import pytest

from adjudication.mcp_server.confirmation import (
    MAX_LIFETIME_S,
    UsedConfirmations,
    call_digest,
    issue_confirmation,
)
from adjudication.mcp_server.server import (
    AdjudicationMCPServer,
    DelegationContext,
    default_registry,
)
from adjudication.runtime.jws import b64, es256_sign, new_key
from adjudication.runtime.tools_registry import Effect

NOW = 1_800_000_000.0
IDP = new_key()
ARGS = {"case_id": "C1"}


def _ctx(officer: str = "off-7") -> DelegationContext:
    return DelegationContext(agent_id="agent-1", agent_ceiling=Effect.IRREVERSIBLE,
                             on_behalf_of=officer, human_roles=frozenset({"officer"}),
                             human_ceiling=Effect.IRREVERSIBLE,
                             case_scope=frozenset({"C1", "C2"}))


def _server(used: UsedConfirmations | None = None, now: float = NOW) -> AdjudicationMCPServer:
    return AdjudicationMCPServer(default_registry(), confirmation_keys={"idp-1": IDP.public_key()},
                                 used_confirmations=used or UsedConfirmations(),
                                 clock=lambda: now)


def _token(**over) -> str:
    kw = dict(officer="off-7", audience="adjudication-mcp", tool="issue_permit",
              arguments=ARGS, now=NOW)
    key = over.pop("key", IDP)
    kid = over.pop("kid", "idp-1")
    kw.update(over)
    return issue_confirmation(key, kid, **kw)


def _call(server, token, args=ARGS, officer="off-7"):
    rid = f"confirm:issue_permit:{args['case_id']}:{officer}"
    return server.call_tool("issue_permit", args, _ctx(officer), {rid: {"token": token}})


def test_input_request_names_what_the_token_must_bind():
    out = _server().call_tool("issue_permit", ARGS, _ctx())
    req = out["inputRequests"][0]
    assert req["audience"] == "adjudication-mcp"
    assert req["call"] and req["mustBeConfirmedBy"] == "off-7"


def test_signed_confirmation_runs_the_call():
    out = _call(_server(), _token())
    assert out["ok"] and out["result"] == {"case_id": "C1", "issued": True}


def test_same_token_cannot_run_twice():
    server, token = _server(), _token()
    assert _call(server, token)["ok"]
    out = _call(server, token)
    assert out["code"] == "NOT_CONFIRMED" and "already used" in out["error"]


def test_replay_is_refused_after_a_restart(tmp_path):
    db = str(tmp_path / "confirmations.db")
    token = _token()
    assert _call(_server(UsedConfirmations(db)), token)["ok"]
    # a new process, same file
    out = _call(_server(UsedConfirmations(db)), token)
    assert out["code"] == "NOT_CONFIRMED" and "already used" in out["error"]


@pytest.mark.parametrize("token_kw, call_kw, reason", [
    ({"key": new_key()}, {}, "bad signature"),                      # forged with the agent's own key
    ({"kid": "idp-9"}, {}, "does not trust"),
    ({"officer": "agent-1"}, {}, "someone else"),
    ({"audience": "billing-mcp"}, {}, "another server"),
    ({"arguments": {"case_id": "C2"}}, {}, "different call"),       # approved for another case
    ({"tool": "request_information"}, {}, "different call"),
    ({"now": NOW - MAX_LIFETIME_S - 60}, {}, "expired"),
    ({"now": NOW + 600}, {}, "future"),
    ({"lifetime_s": 86_400}, {}, "longer than"),
    ({}, {"officer": "off-8"}, "someone else"),                     # carried to another officer's call
])
def test_token_wrong_in_one_way_is_refused(token_kw, call_kw, reason):
    out = _call(_server(), _token(**token_kw), **call_kw)
    assert out["code"] == "NOT_CONFIRMED"
    assert reason in out["error"]


def _forge_header(token: str, header: dict) -> str:
    _, payload, sig = token.split(".")
    h = base64.urlsafe_b64encode(json.dumps(header).encode()).rstrip(b"=").decode()
    return f"{h}.{payload}.{sig}"


@pytest.mark.parametrize("header", [
    {"alg": "none", "typ": "adjudication-confirmation+jwt", "kid": "idp-1"},
    {"alg": "HS256", "typ": "adjudication-confirmation+jwt", "kid": "idp-1"},
    {"alg": "ES256", "typ": "JWT", "kid": "idp-1"},     # some other token from the same provider
])
def test_algorithm_and_type_are_fixed_not_read_from_the_token(header):
    out = _call(_server(), _forge_header(_token(), header))
    assert out["code"] == "NOT_CONFIRMED"


def test_another_token_from_the_same_provider_is_not_a_confirmation():
    """Correctly signed by the trusted key, right claims, but issued as some other
    kind of token, such as a login token. Only the type check stops it."""
    header = {"alg": "ES256", "typ": "JWT", "kid": "idp-1"}
    claims = {"sub": "off-7", "aud": "adjudication-mcp", "iat": int(NOW), "exp": int(NOW) + 60,
              "jti": "login-1", "call": call_digest("issue_permit", ARGS)}
    signing_input = (b64(json.dumps(header).encode()) + "."
                     + b64(json.dumps(claims).encode()))
    token = signing_input + "." + b64(es256_sign(IDP, signing_input.encode()))
    out = _call(_server(), token)
    assert out["code"] == "NOT_CONFIRMED" and "token type" in out["error"]


@pytest.mark.parametrize("garbage", [None, "", "a.b", "not.a.token", 42])
def test_malformed_tokens_are_refused_not_crashed_on(garbage):
    assert _call(_server(), garbage)["code"] == "NOT_CONFIRMED"


def test_no_trusted_key_means_nothing_irreversible_runs():
    server = AdjudicationMCPServer(default_registry(), clock=lambda: NOW)
    assert _call(server, _token())["code"] == "NOT_CONFIRMED"


def test_a_refused_token_is_not_spent():
    """Sent to the wrong call first, it still works for the call it approves."""
    server, token = _server(), _token()
    assert _call(server, token, args={"case_id": "C2"})["code"] == "NOT_CONFIRMED"
    assert _call(server, token)["ok"]


def test_every_refusal_is_recorded_with_its_reason():
    server = _server()
    _call(server, _token(officer="agent-1"))
    assert server.registry.invocations[-1] == (
        "issue_permit", "off-7", False, "confirmation: confirmed by someone else")
