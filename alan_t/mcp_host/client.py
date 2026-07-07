"""Alan_T as an MCP client (Docs_COMPLEX/integrations/MCP.md §1.1).

External MCP servers from config/mcp.yaml appear as registry tools — same
permission gate as native tools (default ASK; per-tool tier overrides in the
server's `tiers:` map). Servers are explicitly configured, never auto-discovered.
"""

from __future__ import annotations

import logging
from contextlib import AsyncExitStack
from typing import Any

from alan_t.core.tools import ToolRegistry

log = logging.getLogger("alan_t.mcp.client")


class McpConnections:
    """Connects configured servers at app startup, registers their tools,
    keeps sessions open for the app's lifetime."""

    def __init__(self, servers_config: dict[str, Any]):
        self._config = servers_config or {}
        self._stack = AsyncExitStack()

    async def connect(self, registry: ToolRegistry) -> None:
        if not self._config:
            return
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        for server_name, cfg in self._config.items():
            try:
                params = StdioServerParameters(
                    command=cfg["command"], args=cfg.get("args", []), env=cfg.get("env"))
                read, write = await self._stack.enter_async_context(stdio_client(params))
                session = await self._stack.enter_async_context(ClientSession(read, write))
                await session.initialize()
                listing = await session.list_tools()
            except Exception as e:
                # one broken server must not take chat down — degrade and say so
                log.error("mcp server '%s' failed to connect: %s", server_name, e)
                continue

            tier_overrides = {k: v.upper() for k, v in cfg.get("tiers", {}).items()}
            for t in listing.tools:
                name = f"{server_name}_{t.name}"

                def make_handler(sess: ClientSession, tool_name: str):
                    async def handler(**kwargs):
                        result = await sess.call_tool(tool_name, kwargs)
                        return "\n".join(c.text for c in result.content if getattr(c, "text", None))
                    return handler

                tool = registry.register(
                    name=name,
                    description=t.description or t.name,
                    parameters=t.inputSchema or {"type": "object", "properties": {}},
                    handler=make_handler(session, t.name),
                    source=f"mcp:{server_name}",
                )
                if t.name in tier_overrides:
                    tool.tier = tier_overrides[t.name]
            log.info("mcp server '%s' connected: %d tools", server_name, len(listing.tools))

    async def close(self) -> None:
        await self._stack.aclose()
