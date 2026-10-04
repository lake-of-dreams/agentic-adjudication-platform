"""Tests for the protocol edges: the MCP server (ADR-0011), the signed A2A agent
card (ADR-0012) and the model client's structured output (ADR-0008).
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from adjudication.a2a.agent_card import (
    AUTHORITY_EXTENSION,
    CARD,
    new_signing_key,
    sign_card,
    verify_card,
)
from adjudication.mcp_server.server import (
    AdjudicationMCPServer,
    DelegationContext,
    default_registry,
)
from adjudication.runtime.llm import LLMConfig, LLMUnavailable, extract_facts
from adjudication.runtime.tools_registry import Effect


def _ctx(**over) -> DelegationContext:
    base = dict(agent_id="agent-1", agent_ceiling=Effect.IRREVERSIBLE, on_behalf_of="off-7",
                human_roles=frozenset({"officer"}), human_ceiling=Effect.IRREVERSIBLE,
                case_scope=frozenset({"C1"}))
    base.update(over)
    return DelegationContext(**base)


# ---------------------------------------------------------------- MCP
def test_unknown_protocol_version_is_refused():
    server = AdjudicationMCPServer(default_registry())
    out = server.list_tools(_ctx(protocol_version="2025-06-18"))
    assert out["code"] == "UNSUPPORTED_PROTOCOL_VERSION"


def test_tool_list_is_filtered_and_marked_private():
    server = AdjudicationMCPServer(default_registry())
    agent_view = server.list_tools(_ctx(human_roles=frozenset({"agent"}), human_ceiling=Effect.READ))
    assert agent_view["cacheScope"] == "private"
    assert agent_view["ttlMs"] > 0
    assert {t["name"] for t in agent_view["tools"]} == {"get_case", "get_criteria"}


def test_irreversible_tool_asks_for_confirmation_first():
    server = AdjudicationMCPServer(default_registry())
    out = server.call_tool("issue_permit", {"case_id": "C1"}, _ctx())
    assert out["resultType"] == "input_required"
    req = out["inputRequests"][0]
    assert req["kind"] == "confirmation" and req["mustBeConfirmedBy"] == "off-7"


def test_confirmation_from_someone_else_is_rejected():
    server = AdjudicationMCPServer(default_registry())
    rid = server.call_tool("issue_permit", {"case_id": "C1"}, _ctx())["inputRequests"][0]["id"]
    out = server.call_tool("issue_permit", {"case_id": "C1"}, _ctx(),
                           {rid: {"confirmed": True, "confirmedBy": "agent-1"}})
    assert out["code"] == "NOT_CONFIRMED"


def test_confirmed_call_runs_once_and_cannot_be_replayed():
    server = AdjudicationMCPServer(default_registry())
    rid = server.call_tool("issue_permit", {"case_id": "C1"}, _ctx())["inputRequests"][0]["id"]
    answer = {rid: {"confirmed": True, "confirmedBy": "off-7"}}
    first = server.call_tool("issue_permit", {"case_id": "C1"}, _ctx(), answer)
    assert first["ok"] and first["result"] == {"case_id": "C1", "issued": True}
    again = server.call_tool("issue_permit", {"case_id": "C1"}, _ctx(), answer)
    assert again["code"] == "NOT_CONFIRMED"


def test_unauthorised_call_is_denied_before_any_confirmation():
    """Asking to confirm a call the caller may not make would leak what tools exist."""
    server = AdjudicationMCPServer(default_registry())
    out = server.call_tool("issue_permit", {"case_id": "C2"}, _ctx())
    assert out["code"] == "TOOL_DENIED"


def test_reads_need_no_confirmation():
    server = AdjudicationMCPServer(default_registry())
    assert server.call_tool("get_case", {"case_id": "C1"}, _ctx())["ok"]
    assert server.call_tool("get_criteria", {}, _ctx(case_scope=frozenset()))["ok"]


# ---------------------------------------------------------------- A2A card
def test_card_has_the_a2a_1_0_shape():
    iface = CARD["supportedInterfaces"][0]
    assert iface["protocolVersion"] == "1.0" and iface["protocolBinding"] == "JSONRPC"
    ext = CARD["capabilities"]["extensions"][0]
    assert ext["uri"] == AUTHORITY_EXTENSION and ext["params"]["mayIssueRefusal"] is False
    for key in ("name", "description", "version", "defaultInputModes",
                "defaultOutputModes", "skills"):
        assert key in CARD


def test_signed_card_verifies_with_the_public_key():
    key = new_signing_key()
    signed = sign_card(CARD, key, kid="k1")
    header = json.loads(_unb64(signed["signatures"][0]["protected"]))
    assert header == {"alg": "ES256", "typ": "JOSE", "kid": "k1"}
    assert verify_card(signed, {"k1": key.public_key()})


def test_verification_ignores_key_order():
    """The signature covers the canonical form, so reordering fields changes nothing."""
    key = new_signing_key()
    signed = sign_card(CARD, key, kid="k1")
    reordered = dict(reversed(list(signed.items())))
    assert verify_card(reordered, {"k1": key.public_key()})


def test_tampered_card_fails():
    key = new_signing_key()
    signed = sign_card(CARD, key, kid="k1")
    signed["capabilities"]["extensions"][0]["params"]["mayIssueRefusal"] = True
    assert not verify_card(signed, {"k1": key.public_key()})


def test_wrong_or_unknown_key_fails():
    signed = sign_card(CARD, new_signing_key(), kid="k1")
    assert not verify_card(signed, {"k1": new_signing_key().public_key()})
    assert not verify_card(signed, {"other": new_signing_key().public_key()})


def test_unsigned_card_fails():
    assert not verify_card(CARD, {"k1": new_signing_key().public_key()})


def _unb64(s: str) -> bytes:
    import base64
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


# ---------------------------------------------------------------- model client
class _FakeServer:
    """A one-route OpenAI-compatible server that records what it was sent."""

    def __init__(self, content):
        self.content = content
        self.requests: list[tuple[dict, dict]] = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                outer.requests.append((dict(self.headers), body))
                reply = json.dumps({"choices": [{"message": {"content": outer.content}}],
                                    "usage": {"prompt_tokens": 10, "completion_tokens": 5}})
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(reply.encode())

            def log_message(self, *_):
                pass

        self.httpd = HTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.httpd.server_port}/v1"

    def close(self):
        self.httpd.shutdown()


@pytest.fixture
def fake():
    servers = []

    def make(content):
        s = _FakeServer(content)
        servers.append(s)
        return s
    yield make
    for s in servers:
        s.close()


GOOD = {"setback_m": 1.4, "height_m": 3.2, "coverage_pct": None,
        "flood_zone_3": False, "listed_building": False}


def test_extraction_requests_a_schema_and_sends_the_key(fake):
    s = fake(json.dumps(GOOD))
    facts, c = extract_facts("Setback 1.4 m. Height 3.2 m.",
                             LLMConfig(s.url, "test-model", api_key="secret"))
    assert facts == GOOD and c.prompt_tokens == 10
    headers, body = s.requests[0]
    assert headers["Authorization"] == "Bearer secret"
    assert body["response_format"]["type"] == "json_schema"
    assert body["response_format"]["json_schema"]["strict"] is True


@pytest.mark.parametrize("bad", [
    {**GOOD, "setback_m": "1.4"},
    {**GOOD, "setback_m": True},
    {**GOOD, "flood_zone_3": "no"},
    {k: v for k, v in GOOD.items() if k != "height_m"},
    {**GOOD, "decision": "GRANT"},
])
def test_wrongly_typed_or_extra_facts_are_refused(fake, bad):
    s = fake(json.dumps(bad))
    with pytest.raises(LLMUnavailable):
        extract_facts("text", LLMConfig(s.url, "test-model"))


def test_no_text_content_is_refused(fake):
    s = fake(None)
    with pytest.raises(LLMUnavailable, match="no text content"):
        extract_facts("text", LLMConfig(s.url, "test-model"))
