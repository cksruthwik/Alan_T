"""The specialist roster (Docs_COMPLEX/architecture/AGENTS.md).

Each agent = persona + tool grant on the shared ToolAgent loop — nothing else.
The grant is the agent's entire authority; skills can never widen it, and every
call still passes the one permission gate. Agents whose backing adapter isn't
configured are simply not registered (bootstrap), so the router never offers
what can't work.
"""

from __future__ import annotations

from alan_t.core.agents.base import AgentContext
from alan_t.core.agents.tool_agent import ToolAgent
from alan_t.core.types import AgentTask


class MemoryAgent(ToolAgent):
    name = "memory"
    description = ("Manage what Alan_T remembers: store facts/preferences/goals, recall or "
                   "review memory, forget wrong or stale entries.")
    role = "CHAT"
    grant = ["recall_memory", "remember_fact", "forget_memory"]


class CodeAgent(ToolAgent):
    name = "code"
    description = ("Search, read, and explain code in the user's mounted repositories; "
                   "answer questions grounded in real source files.")
    role = "CODER"
    grant = ["grep_sources", "read_source", "list_source_files", "search_knowledge"]

    def template_vars(self, task: AgentTask, ctx: AgentContext) -> dict:
        mounts = ctx.files.mounts_summary() if ctx.files else {}
        return {"extra_context": "Mounted sources you can read: "
                                 + (", ".join(f"{k} ({v})" for k, v in mounts.items()) or "none")}


class NotesAgent(ToolAgent):
    name = "notes"
    description = ("Create, append to, read, and search the user's markdown notes "
                   "(Obsidian-compatible folder).")
    role = "CHAT"
    grant = ["note_create", "note_append", "note_read", "note_list", "note_search",
             "search_knowledge"]


class CalendarAgent(ToolAgent):
    name = "calendar"
    description = ("Read and manage the user's Google Calendar: list upcoming events, "
                   "create, move, or cancel them.")
    role = "CHAT"
    grant = ["calendar_list", "calendar_create", "calendar_update", "calendar_delete"]

    def template_vars(self, task: AgentTask, ctx: AgentContext) -> dict:
        from datetime import datetime
        return {"extra_context": f"Current local datetime: {datetime.now():%Y-%m-%d %H:%M (%A)}. "
                                 "Event times must be RFC3339 with offset."}


class EmailAgent(ToolAgent):
    name = "email"
    description = ("Read, triage, and summarize the user's inbox; draft and (with approval) "
                   "send replies; look up contacts by name.")
    role = "CHAT"
    grant = ["email_list", "email_read", "email_send", "resolve_contact", "manage_contact"]


class ResearchAgent(ToolAgent):
    name = "research"
    description = ("Answer questions needing current information from the web: search, read "
                   "sources, synthesize with cited URLs.")
    role = "REASONER"
    grant = ["web_search", "web_fetch", "remember_fact"]

    def template_vars(self, task: AgentTask, ctx: AgentContext) -> dict:
        return {"extra_context": "Cite every claim with its source URL. Search first, then "
                                 "fetch the most promising results before answering."}


class BrowserAgent(ToolAgent):
    name = "browser"
    description = ("Operate a real browser on a specific page: navigate, click, fill forms, "
                   "extract what static fetching can't reach.")
    role = "REASONER"
    grant = ["browser_run", "web_fetch"]


class AutomationAgent(ToolAgent):
    name = "automation"
    description = ("Report on scheduled automations and past task runs; send notifications; "
                   "kick off multi-step goals through the task planner.")
    role = "CHAT"
    grant = ["list_automations", "run_automation", "list_task_runs", "notify", "run_goal"]


class DocumentsAgent(ToolAgent):
    name = "documents"
    description = ("Draft and revise longer writing (reports, letters, posts) as versioned "
                   "documents the user can retrieve later.")
    role = "CHAT"
    grant = ["document_create", "document_update", "document_read", "document_list"]
