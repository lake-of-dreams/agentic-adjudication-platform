"""Tool authorisation: entitlement, effect ceiling, argument scope.

Checking entitlement on its own is a confused deputy. Being allowed a tool says
nothing about how big an effect it may have or which records it may touch.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import IntEnum


class Effect(IntEnum):
    READ = 0          # no state change
    WRITE = 1         # reversible state change
    IRREVERSIBLE = 2  # notifies a third party, spends money, or cannot be undone


class ToolDenied(PermissionError):
    pass


@dataclass(frozen=True)
class Principal:
    id: str
    roles: frozenset[str]
    ceiling: Effect
    # Case ids this principal may touch. Empty set = all (supervisor).
    case_scope: frozenset[str] = field(default_factory=frozenset)


@dataclass(frozen=True)
class Tool:
    name: str
    effect: Effect
    required_roles: frozenset[str]
    handler: Callable[..., object]
    description: str = ""


@dataclass
class ToolRegistry:
    tools: dict[str, Tool] = field(default_factory=dict)
    invocations: list[tuple[str, str, bool, str]] = field(default_factory=list)

    def register(self, tool: Tool) -> None:
        self.tools[tool.name] = tool

    def manifest(self, principal: Principal) -> list[str]:
        """Filtered manifest. An agent cannot be talked into calling a tool it
        was never shown."""
        return sorted(
            name for name, t in self.tools.items()
            if t.required_roles & principal.roles and t.effect <= principal.ceiling
        )

    def invoke(self, name: str, principal: Principal, agent_ceiling: Effect, **kwargs):
        tool = self.tools.get(name)
        if tool is None:
            self._record(name, principal.id, False, "unregistered tool")
            raise ToolDenied(f"tool {name!r} is not registered")

        # 1. entitlement
        if not (tool.required_roles & principal.roles):
            self._record(name, principal.id, False, "role")
            raise ToolDenied(f"{principal.id} lacks a role in {sorted(tool.required_roles)}")

        # 2. effect ceiling, the lower of agent and human
        effective = min(agent_ceiling, principal.ceiling)
        if tool.effect > effective:
            self._record(name, principal.id, False, "effect ceiling")
            raise ToolDenied(
                f"{name} has effect {tool.effect.name} above ceiling {Effect(effective).name}")

        # 3. argument scope
        case_id = kwargs.get("case_id")
        if case_id and principal.case_scope and case_id not in principal.case_scope:
            self._record(name, principal.id, False, "argument scope")
            raise ToolDenied(f"{principal.id} is not scoped to case {case_id}")

        self._record(name, principal.id, True, "ok")
        return tool.handler(**kwargs)

    def _record(self, tool: str, who: str, allowed: bool, why: str) -> None:
        self.invocations.append((tool, who, allowed, why))
