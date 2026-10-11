"""MCP server with on-behalf-of authorisation.

Every call carries the invoking human's identity and the server recomputes
min(agent_ceiling, human_ceiling) itself instead of taking the agent's word for
it. The 2026-07-28 specification made the protocol core stateless: there is no
session, and every request carries its own protocol version and client details.
Authorisation context travels per call for the same reason.

Two further parts of that specification shape this server (ADR-0011).

* Tool lists carry cache hints. The list here is filtered for each caller, so it
  is marked private; a shared cache would show one officer's tools to another.
* A tool can ask for input mid-call. The server answers "input required" and the
  client retries the same call with the answers attached. An irreversible tool
  uses this to stop for an explicit confirmation from the human it acts for,
  which the agent cannot supply on its own.

The confirmation is a short-lived token signed by the identity provider and
bound to the officer, this server and the exact call (ADR-0013). The client
carries it and cannot make one.

The shapes below are modelled on the specification's description; they are not
a wire-level implementation of the protocol.
"""
from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field

from cryptography.hazmat.primitives.asymmetric import ec

from adjudication.mcp_server.confirmation import (
    ConfirmationRejected,
    UsedConfirmations,
    call_digest,
    verify_confirmation,
)
from adjudication.runtime.tools_registry import (
    ALL_CASES,
    Effect,
    Principal,
    Tool,
    ToolDenied,
    ToolRegistry,
)

SUPPORTED_PROTOCOL_VERSIONS = frozenset({"2026-07-28"})

# How long a client may cache this caller's tool list.
TOOL_LIST_TTL_MS = 60_000


@dataclass(frozen=True)
class DelegationContext:
    """Travels with every tool call."""
    agent_id: str
    agent_ceiling: Effect
    on_behalf_of: str
    human_roles: frozenset[str]
    human_ceiling: Effect
    case_scope: frozenset[str]
    protocol_version: str = "2026-07-28"


@dataclass
class AdjudicationMCPServer:
    registry: ToolRegistry
    # Identity provider keys that may sign confirmations, by key id. None
    # configured means no irreversible call can be confirmed: fail closed.
    confirmation_keys: dict[str, ec.EllipticCurvePublicKey] = field(default_factory=dict)
    audience: str = "adjudication-mcp"
    # Spent confirmation ids. Pass a file path in production so they survive a restart.
    used_confirmations: UsedConfirmations = field(default_factory=UsedConfirmations)
    clock: Callable[[], float] = time.time

    def list_tools(self, ctx: DelegationContext) -> dict:
        """Filtered per caller. See ToolRegistry.manifest."""
        refused = self._check_version(ctx)
        if refused:
            return refused
        principal = self._principal(ctx)
        tools = [{"name": n,
                  "description": self.registry.tools[n].description,
                  "effect": self.registry.tools[n].effect.name}
                 for n in self.registry.manifest(principal)]
        return {"tools": tools, "ttlMs": TOOL_LIST_TTL_MS, "cacheScope": "private"}

    def call_tool(self, name: str, arguments: dict, ctx: DelegationContext,
                  input_responses: dict | None = None) -> dict:
        refused = self._check_version(ctx)
        if refused:
            return refused
        principal = self._principal(ctx)
        try:
            # Authorise before asking anyone to confirm. A confirmation request
            # for a call the caller may not make would leak what tools exist.
            tool = self.registry.authorise(name, principal, ctx.agent_ceiling, **arguments)
        except ToolDenied as exc:
            # return denials instead of raising, so the agent can react to them.
            # recorded either way.
            return {"ok": False, "error": str(exc), "code": "TOOL_DENIED"}

        if tool.effect is Effect.IRREVERSIBLE:
            request_id = f"confirm:{name}:{arguments.get('case_id', '')}:{ctx.on_behalf_of}"
            answer = (input_responses or {}).get(request_id)
            if answer is None:
                return {"resultType": "input_required",
                        "inputRequests": [{
                            "id": request_id, "kind": "confirmation",
                            "message": f"Confirm {name} for case {arguments.get('case_id')}. "
                                       "This cannot be undone.",
                            "mustBeConfirmedBy": ctx.on_behalf_of,
                            # what the identity provider must bind the token to
                            "audience": self.audience,
                            "call": call_digest(name, arguments)}]}
            try:
                verify_confirmation(
                    answer.get("token") if isinstance(answer, dict) else None,
                    trusted_keys=self.confirmation_keys, audience=self.audience,
                    officer=ctx.on_behalf_of, tool=name, arguments=arguments,
                    now=self.clock(), used=self.used_confirmations)
            except ConfirmationRejected as exc:
                self.registry._record(name, principal.id, False, f"confirmation: {exc.reason}")
                return {"ok": False, "code": "NOT_CONFIRMED",
                        "error": f"{name} needs confirmation from {ctx.on_behalf_of}: "
                                 f"{exc.reason}"}

        self.registry._record(name, principal.id, True, "ok")
        return {"ok": True, "result": tool.handler(**arguments),
                "authorised_as": ctx.on_behalf_of, "agent": ctx.agent_id}

    @staticmethod
    def _check_version(ctx: DelegationContext) -> dict | None:
        """Fail closed on a protocol version this server does not implement."""
        if ctx.protocol_version not in SUPPORTED_PROTOCOL_VERSIONS:
            return {"ok": False, "code": "UNSUPPORTED_PROTOCOL_VERSION",
                    "error": f"protocol version {ctx.protocol_version!r} is not supported; "
                             f"supported: {sorted(SUPPORTED_PROTOCOL_VERSIONS)}"}
        return None

    @staticmethod
    def _principal(ctx: DelegationContext) -> Principal:
        return Principal(id=ctx.on_behalf_of, roles=ctx.human_roles,
                         ceiling=ctx.human_ceiling, case_scope=ctx.case_scope)


def default_registry() -> ToolRegistry:
    r = ToolRegistry()
    r.register(Tool("get_case", Effect.READ, frozenset({"officer", "agent"}),
                    lambda case_id: {"case_id": case_id, "status": "open"},
                    "Read a case file."))
    r.register(Tool("get_criteria", Effect.READ, frozenset({"officer", "agent"}),
                    lambda: ["C1", "C2", "C3", "C4", "C5"],
                    "List published adjudication criteria.", case_scoped=False))
    r.register(Tool("request_information", Effect.WRITE, frozenset({"officer", "agent"}),
                    lambda case_id, items: {"case_id": case_id, "requested": items},
                    "Ask the applicant for further information."))
    r.register(Tool("issue_permit", Effect.IRREVERSIBLE, frozenset({"officer"}),
                    lambda case_id: {"case_id": case_id, "issued": True},
                    "Issue a permit. Irreversible; officer only."))
    return r


__all__ = ["ALL_CASES", "AdjudicationMCPServer", "DelegationContext", "default_registry"]
