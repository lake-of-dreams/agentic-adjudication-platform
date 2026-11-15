"""The MCP server driven by the official SDK's client over the real protocol (ADR-0015).

test_protocols.py and test_confirmation.py call the server as Python. These
tests go through `mcp.Client`, so the tool list, the denial, the confirmation
request and the retry are the messages a real client would exchange.
"""
from __future__ import annotations

import os
import sys
import time

import anyio
import pytest

pytest.importorskip("mcp")

import mcp.types as types  # noqa: E402
from mcp import Client, StdioServerParameters  # noqa: E402

from adjudication.mcp_server.confirmation import issue_confirmation  # noqa: E402
from adjudication.mcp_server.server import (  # noqa: E402
    AdjudicationMCPServer,
    DelegationContext,
    default_registry,
)
from adjudication.mcp_server.wire import build_wire_server  # noqa: E402
from adjudication.runtime.jws import new_key  # noqa: E402
from adjudication.runtime.tools_registry import Effect  # noqa: E402

IDP = new_key()


def _ctx(officer="off-7", roles=("officer",), ceiling=Effect.IRREVERSIBLE) -> DelegationContext:
    return DelegationContext("agent-1", Effect.IRREVERSIBLE, officer, frozenset(roles), ceiling,
                             frozenset({"C1"}))


def _server(ctx: DelegationContext):
    core = AdjudicationMCPServer(default_registry(), confirmation_keys={"idp-1": IDP.public_key()})
    return build_wire_server(core, lambda _request: ctx)


def _signed_by(key, officer="off-7", case="C1"):
    async def confirm(_ctx, _params):
        token = issue_confirmation(key, "idp-1", officer=officer, audience="adjudication-mcp",
                                   tool="issue_permit", arguments={"case_id": case}, now=time.time())
        return types.ElicitResult(action="accept", content={"token": token})
    return confirm


def run(coro_fn):
    return anyio.run(coro_fn)


def test_the_client_speaks_the_stateless_revision_and_sees_a_private_filtered_list():
    async def go():
        async with Client(_server(_ctx())) as officer:
            listed = await officer.list_tools()
            assert officer.protocol_version == "2026-07-28"
            assert listed.cache_scope == "private" and listed.ttl_ms == 60_000
            assert "issue_permit" in {t.name for t in listed.tools}
        async with Client(_server(_ctx(roles=("agent",), ceiling=Effect.WRITE))) as agent:
            names = {t.name for t in (await agent.list_tools()).tools}
            assert "issue_permit" not in names and "get_case" in names
    run(go)


def test_a_call_outside_the_officers_cases_comes_back_as_an_error_result():
    async def go():
        async with Client(_server(_ctx())) as c:
            ok = await c.call_tool("get_case", {"case_id": "C1"})
            denied = await c.call_tool("get_case", {"case_id": "C9"})
        assert ok.is_error is False and ok.structured_content["authorised_as"] == "off-7"
        assert denied.is_error is True and denied.structured_content["code"] == "TOOL_DENIED"
    run(go)


def test_an_irreversible_call_runs_once_the_officers_signed_confirmation_arrives():
    asked = []

    async def confirm(ctx, params):
        asked.append(params.message)
        return await _signed_by(IDP)(ctx, params)

    async def go():
        async with Client(_server(_ctx()), elicitation_callback=confirm) as c:
            return await c.call_tool("issue_permit", {"case_id": "C1"})
    out = run(go)
    assert out.is_error is False and out.structured_content["result"]["issued"] is True
    assert len(asked) == 1 and "off-7" in asked[0] and "cannot be undone" in asked[0]


def test_a_token_the_agent_signed_for_itself_issues_nothing():
    async def go():
        async with Client(_server(_ctx()), elicitation_callback=_signed_by(new_key())) as c:
            return await c.call_tool("issue_permit", {"case_id": "C1"})
    out = run(go)
    assert out.is_error is True and out.structured_content["code"] == "NOT_CONFIRMED"


def test_a_declined_confirmation_issues_nothing():
    async def decline(_ctx, _params):
        return types.ElicitResult(action="decline")

    async def go():
        async with Client(_server(_ctx()), elicitation_callback=decline,
                          input_required_max_rounds=2) as c:
            return await c.call_tool("issue_permit", {"case_id": "C1"})
    # The server keeps asking; the client gives up. Either way no permit.
    with pytest.raises(Exception) as err:  # noqa: PT011
        run(go)
    assert "issued" not in str(err.value)


def test_the_same_confirmation_cannot_issue_a_second_permit():
    tokens = []

    async def confirm_once(_ctx, _params):
        if not tokens:
            tokens.append(issue_confirmation(IDP, "idp-1", officer="off-7",
                                             audience="adjudication-mcp", tool="issue_permit",
                                             arguments={"case_id": "C1"}, now=time.time()))
        return types.ElicitResult(action="accept", content={"token": tokens[0]})

    async def go():
        async with Client(_server(_ctx()), elicitation_callback=confirm_once) as c:
            first = await c.call_tool("issue_permit", {"case_id": "C1"})
            second = await c.call_tool("issue_permit", {"case_id": "C1"})
        return first, second
    first, second = run(go)
    assert first.is_error is False
    assert second.is_error is True and "already used" in second.structured_content["error"]


def test_the_stdio_entry_point_serves_one_officer_and_fails_closed_without_a_key():
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "adjudication.mcp_server"],
        env={**os.environ, "ADJUDICATION_OFFICER": "off-7", "ADJUDICATION_CASES": "C1"})

    async def go():
        async with Client(params, elicitation_callback=_signed_by(IDP)) as c:
            read = await c.call_tool("get_case", {"case_id": "C1"})
            permit = await c.call_tool("issue_permit", {"case_id": "C1"})
        return read, permit
    read, permit = run(go)
    assert read.is_error is False
    # No identity provider key was configured, so even a well-formed token is refused.
    assert permit.is_error is True and permit.structured_content["code"] == "NOT_CONFIRMED"
