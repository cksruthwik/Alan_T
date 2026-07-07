"""Alan_T as an MCP server (Docs_COMPLEX/integrations/MCP.md §1.2).

Exposes over stdio, to any MCP client the user runs (Claude Code, etc.):
- every tool in the registry (same permission gate — ASK-tier tools return an
  approval-required message instead of executing; MCP gets no side door),
- every agent, as `agent_<name>(message)`,
- the skill library (`list_skills` / `get_skill`).

Entry point: `alan-mcp` (see pyproject).
"""

from __future__ import annotations

import json
import logging

import anyio
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from alan_t.core.tools import NeedsApproval
from alan_t.core.types import AgentTask, IncomingMessage, MessageKind

log = logging.getLogger("alan_t.mcp.server")

_MESSAGE_SCHEMA = {
    "type": "object",
    "properties": {"message": {"type": "string", "description": "The user message for this agent"}},
    "required": ["message"],
}


def build_server() -> Server:
    # Import here so `alan-mcp --help`-style failures stay cheap and the app
    # package never imports the MCP SDK unless serving.
    from alan_t.app.bootstrap import build

    app = build()
    server = Server("alan_t")

    def _agents() -> dict[str, object]:
        return dict(app.agents)  # the full roster, whatever this config registered

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        tools = [
            Tool(name=t["name"], description=f"[{t['tier']}] {t['description']}",
                 inputSchema=t["parameters"])
            for t in app.tools.specs()
        ]
        tools += [
            Tool(name=f"agent_{name}",
                 description=f"Run the {name} agent: {agent.description}",
                 inputSchema=_MESSAGE_SCHEMA)
            for name, agent in _agents().items()
        ]
        tools.append(Tool(name="list_skills", description="List Alan_T's reusable skills (name + trigger).",
                          inputSchema={"type": "object", "properties": {}}))
        tools.append(Tool(name="get_skill", description="Get a skill's full instruction body by name.",
                          inputSchema={"type": "object", "properties": {"name": {"type": "string"}},
                                       "required": ["name"]}))
        return tools

    @server.call_tool()
    async def call_tool(name: str, args: dict) -> list[TextContent]:
        try:
            if name == "list_skills":
                result = app.skills.menu() or "(no skills)"
            elif name == "get_skill":
                skill = app.skills.get(args["name"])
                result = skill.body if skill else f"unknown skill: {args['name']}"
            elif name.startswith("agent_"):
                agent = _agents().get(name.removeprefix("agent_"))
                if agent is None:
                    result = f"unknown agent: {name}"
                else:
                    r = await agent.run(
                        AgentTask(message=IncomingMessage(kind=MessageKind.TEXT,
                                                          text=args["message"], channel="mcp")),
                        app.ctx,
                    )
                    result = r.response
            else:
                result = await app.tools.execute(name, args)
        except NeedsApproval as e:
            result = f"NOT EXECUTED — {e}. Approve it in Alan_T (web/Telegram) and retry."
        except PermissionError as e:
            result = f"REFUSED — {e}"
        if not isinstance(result, str):
            result = json.dumps(result, default=str)
        return [TextContent(type="text", text=result)]

    return server


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    server = build_server()

    async def run() -> None:
        async with stdio_server() as (read, write):
            await server.run(read, write, server.create_initialization_options())

    anyio.run(run)


if __name__ == "__main__":
    main()
