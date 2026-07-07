"""Tool registry + permission gate (Docs_COMPLEX/ai/TOOL_CATALOG.md, security/TOOL_PERMISSIONS.md).

One registry, one gate. Native tools, MCP-provided tools, and skill-invoked tools
all enter here and are gated identically — MCP gets no side door.
Tiers come from config/permissions.yaml; unlisted tools default to ASK.
"""

from __future__ import annotations

import inspect
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger("alan_t.tools")

ALLOW, ASK, DENY = "ALLOW", "ASK", "DENY"


class NeedsApproval(Exception):
    """ASK-tier tool invoked without an approval channel — surfaced honestly."""


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]  # JSON schema
    handler: Callable[..., Awaitable[Any]]
    tier: str = ASK
    source: str = "native"  # native | mcp:<server>


@dataclass
class ToolRegistry:
    _tools: dict[str, Tool] = field(default_factory=dict)
    _tiers: dict[str, str] = field(default_factory=dict)  # from permissions.yaml

    def set_tiers(self, tiers: dict[str, str]) -> None:
        self._tiers = {k: v.upper() for k, v in tiers.items()}
        for t in self._tools.values():
            t.tier = self._tiers.get(t.name, ASK)

    def register(
        self,
        name: str,
        description: str,
        parameters: dict[str, Any],
        handler: Callable[..., Awaitable[Any]],
        source: str = "native",
    ) -> Tool:
        if name in self._tools:
            raise ValueError(f"tool already registered: {name}")
        tool = Tool(name, description, parameters, handler,
                    tier=self._tiers.get(name, ASK), source=source)
        self._tools[name] = tool
        log.info("tool registered name=%s tier=%s source=%s", name, tool.tier, source)
        return tool

    def get(self, name: str) -> Tool:
        return self._tools[name]

    def has(self, name: str) -> bool:
        return name in self._tools

    def names(self) -> list[str]:
        return sorted(self._tools)

    def specs(self) -> list[dict[str, Any]]:
        """Progressive-disclosure menu / MCP listing: name+description+schema only."""
        return [
            {"name": t.name, "description": t.description, "parameters": t.parameters,
             "tier": t.tier, "source": t.source}
            for t in self._tools.values()
        ]

    async def execute(self, name: str, args: dict[str, Any], *, approved: bool = False) -> Any:
        """The permission gate. Every tool call — agent, skill, or MCP — routes here."""
        from alan_t.core.observability import TOOL_EXECUTIONS

        tool = self._tools.get(name)
        if tool is None:
            raise KeyError(f"unknown tool: {name}")
        if tool.tier == DENY:
            TOOL_EXECUTIONS.labels(tool=name, tier=DENY, outcome="refused").inc()
            raise PermissionError(f"tool '{name}' is DENY-tier; refusing")
        if tool.tier == ASK and not approved:
            TOOL_EXECUTIONS.labels(tool=name, tier=ASK, outcome="needs_approval").inc()
            raise NeedsApproval(f"tool '{name}' requires approval before it runs")
        try:
            result = tool.handler(**args)
            if inspect.isawaitable(result):
                result = await result
        except Exception:
            TOOL_EXECUTIONS.labels(tool=name, tier=tool.tier, outcome="error").inc()
            raise
        TOOL_EXECUTIONS.labels(tool=name, tier=tool.tier, outcome="ok").inc()
        log.info("tool executed name=%s source=%s", name, tool.source)
        return result
