"""Run the adjudication tools as an MCP server on standard input and output.

    ADJUDICATION_OFFICER=off-7 ADJUDICATION_CASES=C1,C2 python -m adjudication.mcp_server

An MCP client such as a desktop assistant starts this process itself, so the
process belongs to one officer, named in the environment by whoever configured
the client. ADJUDICATION_IDP_KEY may point at the identity provider's public
key in PEM form. Without it no confirmation can be verified, so issue_permit
always stops at the confirmation request: fail closed.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import anyio
from cryptography.hazmat.primitives.serialization import load_pem_public_key
from mcp.server.stdio import stdio_server

from adjudication.mcp_server.server import (
    AdjudicationMCPServer,
    DelegationContext,
    default_registry,
)
from adjudication.mcp_server.wire import build_wire_server
from adjudication.runtime.tools_registry import Effect


def main() -> int:
    officer = os.getenv("ADJUDICATION_OFFICER", "").strip()
    if not officer:
        print("ADJUDICATION_OFFICER is not set: refusing to serve tools for nobody", file=sys.stderr)
        return 2
    cases = frozenset(c.strip() for c in os.getenv("ADJUDICATION_CASES", "").split(",") if c.strip())
    keys = {}
    if path := os.getenv("ADJUDICATION_IDP_KEY"):
        keys[os.getenv("ADJUDICATION_IDP_KID", "idp-1")] = load_pem_public_key(Path(path).read_bytes())

    core = AdjudicationMCPServer(default_registry(), confirmation_keys=keys)
    ctx = DelegationContext(agent_id="mcp-stdio", agent_ceiling=Effect.IRREVERSIBLE,
                            on_behalf_of=officer, human_roles=frozenset({"officer"}),
                            human_ceiling=Effect.IRREVERSIBLE, case_scope=cases)
    server = build_wire_server(core, lambda _request: ctx)

    async def serve() -> None:
        async with stdio_server() as (read, write):
            await server.run(read, write, server.create_initialization_options())

    anyio.run(serve)
    return 0


if __name__ == "__main__":
    sys.exit(main())
