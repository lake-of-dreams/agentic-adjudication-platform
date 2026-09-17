"""MCP server with on-behalf-of authorisation.

Every call carries the invoking human's identity and the server recomputes
min(agent_ceiling, human_ceiling) itself instead of taking the agent's word for
it. The 2026-07-28 spec dropped sessions, so auth context travels per call
regardless.
"""
from __future__ import annotations

from dataclasses import dataclass

from adjudication.runtime.tools_registry import Effect, Principal, Tool, ToolDenied, ToolRegistry


@dataclass(frozen=True)
class DelegationContext:
    """Travels with every tool call."""
    agent_id: str
    agent_ceiling: Effect
    on_behalf_of: str
    human_roles: frozenset[str]
    human_ceiling: Effect
    case_scope: frozenset[str]


class AdjudicationMCPServer:
    def __init__(self, registry: ToolRegistry) -> None:
        self.registry = registry

    def list_tools(self, ctx: DelegationContext) -> list[dict]:
        """Filtered per caller. See ToolRegistry.manifest."""
        principal = self._principal(ctx)
        return [{"name": n,
                 "description": self.registry.tools[n].description,
                 "effect": self.registry.tools[n].effect.name}
                for n in self.registry.manifest(principal)]

    def call_tool(self, name: str, arguments: dict, ctx: DelegationContext) -> dict:
        principal = self._principal(ctx)
        try:
            result = self.registry.invoke(
                name, principal, agent_ceiling=ctx.agent_ceiling, **arguments)
            return {"ok": True, "result": result,
                    "authorised_as": ctx.on_behalf_of, "agent": ctx.agent_id}
        except ToolDenied as exc:
            # return denials instead of raising, so the agent can react to them.
            # recorded either way.
            return {"ok": False, "error": str(exc), "code": "TOOL_DENIED"}

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
                    "List published adjudication criteria."))
    r.register(Tool("request_information", Effect.WRITE, frozenset({"officer", "agent"}),
                    lambda case_id, items: {"case_id": case_id, "requested": items},
                    "Ask the applicant for further information."))
    r.register(Tool("issue_permit", Effect.IRREVERSIBLE, frozenset({"officer"}),
                    lambda case_id: {"case_id": case_id, "issued": True},
                    "Issue a permit. Irreversible; officer only."))
    return r
