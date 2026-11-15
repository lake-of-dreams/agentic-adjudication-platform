"""The same server, speaking the Model Context Protocol on the wire.

server.py holds the authorisation logic and models the protocol's shapes as
plain dictionaries. This module puts the official `mcp` SDK in front of it, so
a real MCP client can list the tools, call one, and be stopped for a signed
confirmation (ADR-0015). No rule lives here: every decision is still made by
AdjudicationMCPServer.

The caller's identity does not come from the request. `context_for` is called
once per request and must return who the agent is acting for. Over standard
input and output the process belongs to one officer, so it returns a fixed
context. Over HTTP it has to read a verified access token, which this
repository does not do.

Needs the `mcp` extra: pip install -e ".[mcp]"
"""
from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import mcp.types as types
from mcp.server.lowlevel.server import Server

from adjudication.mcp_server.server import (
    TOOL_LIST_TTL_MS,
    AdjudicationMCPServer,
    DelegationContext,
)

# The JSON Schema each tool's arguments must match. The registry checks who may
# call a tool; these tell a client what a call looks like.
TOOL_ARGUMENTS: dict[str, dict[str, Any]] = {
    "get_case": {"type": "object", "properties": {"case_id": {"type": "string"}},
                 "required": ["case_id"], "additionalProperties": False},
    "get_criteria": {"type": "object", "properties": {}, "additionalProperties": False},
    "request_information": {
        "type": "object",
        "properties": {"case_id": {"type": "string"},
                       "items": {"type": "array", "items": {"type": "string"}}},
        "required": ["case_id", "items"], "additionalProperties": False},
    "issue_permit": {"type": "object", "properties": {"case_id": {"type": "string"}},
                     "required": ["case_id"], "additionalProperties": False},
}

# What the server asks the officer's client for when a call needs confirming.
CONFIRMATION_FORM = {
    "type": "object",
    "properties": {"token": {
        "type": "string",
        "description": "The signed confirmation from the identity provider for this exact call."}},
    "required": ["token"],
}


def _text(payload: dict, *, is_error: bool = False) -> types.CallToolResult:
    return types.CallToolResult(content=[types.TextContent(type="text", text=json.dumps(payload))],
                                structured_content=payload, is_error=is_error)


def build_wire_server(core: AdjudicationMCPServer,
                      context_for: Callable[[Any], DelegationContext]) -> Server:
    async def list_tools(ctx, _params) -> types.ListToolsResult:
        listed = core.list_tools(context_for(ctx))
        tools = [types.Tool(name=t["name"], description=f"{t['description']} Effect: {t['effect']}.",
                            input_schema=TOOL_ARGUMENTS.get(t["name"], {"type": "object"}))
                 for t in listed.get("tools", [])]
        # private: the list is filtered for this caller (ADR-0011)
        return types.ListToolsResult(tools=tools, ttl_ms=TOOL_LIST_TTL_MS, cache_scope="private")

    async def call_tool(ctx, params: types.CallToolRequestParams):
        arguments = params.arguments or {}
        answers = {}
        for rid, response in (params.input_responses or {}).items():
            # Only an accepted form carries a token. A declined or cancelled
            # confirmation is passed on as no answer at all.
            if isinstance(response, types.ElicitResult) and response.action == "accept":
                answers[rid] = {"token": (response.content or {}).get("token")}
        out = core.call_tool(params.name, arguments, context_for(ctx), answers or None)

        if out.get("resultType") == "input_required":
            requests = {}
            for req in out["inputRequests"]:
                message = (f"{req['message']} Must be confirmed by {req['mustBeConfirmedBy']}. "
                           f"The token must be for audience {req['audience']} and call {req['call']}.")
                requests[req["id"]] = types.ElicitRequest(
                    method="elicitation/create",
                    params=types.ElicitRequestFormParams(
                        mode="form", message=message, requested_schema=CONFIRMATION_FORM))
            return types.InputRequiredResult(result_type="input_required", input_requests=requests)
        if out.get("ok"):
            return _text({"result": out["result"], "authorised_as": out["authorised_as"]})
        return _text({"code": out.get("code"), "error": out.get("error")}, is_error=True)

    return Server("adjudication", on_list_tools=list_tools, on_call_tool=call_tool)
