# Integration — MCP (Model Context Protocol)

Status: Future (PRD roadmap item) — design position recorded now so nothing painted into a corner.

## Position

MCP is the emerging standard for tool/context interop between AI systems. Alan_T's relationship to it, when implemented:

1. **Alan_T as MCP client (the valuable direction):** external MCP servers (filesystem, GitHub, Slack, home automation…) appear as tools. The integration point is the existing tool registry — an `McpToolAdapter` wraps each discovered MCP tool as a `ToolSpec` ([TOOL_CATALOG.md](../ai/TOOL_CATALOG.md) §1), which means:
   - MCP tools pass the **same permission gate** as native tools — tier assigned at registration (default ASK, per the registry rule), audited identically. MCP does not get a side door around [TOOL_PERMISSIONS.md](../security/TOOL_PERMISSIONS.md).
   - MCP server configs live in `config/mcp.yaml` (command/url, allowed tools, tier overrides); servers are explicitly added by the user, never auto-discovered.
2. **Alan_T as MCP server (maybe, later):** exposing `search_knowledge`/`recall_memory` to other AI clients the user runs. Deferred — it inverts the trust model (another agent reading personal memory) and needs its own threat-model pass before any code.

## Why Not Now

Phases 1–7 have a closed, auditable tool surface; adding third-party tool processes mid-foundation multiplies the injection/permission surface while the gate mechanics are still proving out. The architecture already accommodates it (tools are registry entries; the gate is tool-agnostic), so deferral costs nothing structurally.

## Skills Are the Natural Consumer of MCP Tools

When MCP lands, MCP-provided tools become registry entries like any other ([TOOL_CATALOG.md](../ai/TOOL_CATALOG.md)), which means a **skill** ([SKILLS.md](../ai/SKILLS.md)) can declare them in `required_tools` and orchestrate them. A "triage my GitHub notifications" skill, for instance, would be a thin instruction body over an MCP GitHub server's tools — gated like everything else. MCP supplies the tools; skills supply the reusable know-how for using them. The two features compose cleanly and were designed to.

## Trigger to Revisit

First concrete want that MCP solves cheaper than a native adapter — e.g., a maintained MCP server for a service Alan_T needs (GitHub, Home Assistant). At that point: implement the client adapter, register with default-ASK tiers, contract-test against the reference servers, and record the ADR.
