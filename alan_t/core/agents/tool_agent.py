"""ToolAgent — the shared agentic loop (Docs_COMPLEX/architecture/AGENTS.md §2).

Every specialist agent is: a persona prompt + a tool grant + this loop.
The loop: model proposes tool calls → the ONE permission gate executes them →
results go back → repeat until the model answers in text (or rounds run out).

ASK-tier calls become pending approvals (core/approvals.py): the model is told
the call is pending and finishes its turn saying so; approval executes later.
`required_tools` of any selected skill must sit inside the agent's grant —
a skill can never widen authority (SKILLS.md §5).
"""

from __future__ import annotations

import json
import logging

from alan_t.core.agents.base import AgentContext
from alan_t.core.observability import AGENT_TURNS
from alan_t.core.prompts import render
from alan_t.core.tools import NeedsApproval
from alan_t.core.types import (
    AgentResult,
    AgentStatus,
    AgentTask,
    ChatMessage,
    ChatRequest,
    ToolCall,
    ToolSpec,
)

log = logging.getLogger("alan_t.agents")

MAX_ROUNDS = 6  # runaway-loop guard (WORKFLOWS.md: bounded agent turns)


class ToolAgent:
    """Subclasses set: name, description, role, grant, template (+ template vars)."""

    name = "tool_agent"
    description = ""
    role = "CHAT"           # model role this agent's reasoning runs on
    grant: list[str] = []   # tool names this agent may call — its entire authority
    template = "agent_generic.j2"
    tools: list[ToolSpec] = []

    def template_vars(self, task: AgentTask, ctx: AgentContext) -> dict:
        return {}

    def _granted_specs(self, ctx: AgentContext) -> list[dict]:
        return [s for s in ctx.tools.specs() if s["name"] in self.grant]

    async def _memory(self, task: AgentTask, ctx: AgentContext) -> list:
        try:
            return await ctx.memory.recall(task.message.text) if task.message.text else []
        except Exception:
            return []

    async def run(self, task: AgentTask, ctx: AgentContext) -> AgentResult:
        specs = self._granted_specs(ctx)
        system = render(
            self.template,
            user_name=ctx.user_name,
            agent_name=self.name,
            agent_description=self.description,
            memory_facts=await self._memory(task, ctx),
            skills=task.skills,
            project_instructions=task.project_instructions,
            **{"extra_context": "", **self.template_vars(task, ctx)},
        )
        messages = [ChatMessage(role="system", content=system), *task.history,
                    ChatMessage(role="user", content=task.message.text)]

        calls: list[ToolCall] = []
        status = AgentStatus.OK
        resp = None
        for _ in range(MAX_ROUNDS):
            resp = await ctx.llm.complete(self.role, ChatRequest(messages=messages, tools=specs))
            if not resp.tool_calls:
                break
            messages.append(ChatMessage(role="assistant", content=resp.text,
                                        tool_calls=resp.tool_calls))
            for tc in resp.tool_calls:
                try:
                    result = await ctx.tools.execute(tc.name, tc.arguments)
                    outcome = result if isinstance(result, str) else json.dumps(result, default=str)
                except NeedsApproval:
                    approval = ctx.approvals.create(tc.name, tc.arguments)
                    outcome = (f"NOT EXECUTED — '{tc.name}' needs the user's approval. "
                               f"Approval request #{approval.id} was created; tell the user "
                               f"to approve or deny it (Telegram buttons or the approvals API).")
                    status = AgentStatus.NEEDS_APPROVAL
                except PermissionError as e:
                    outcome = f"REFUSED by policy: {e}"
                except Exception as e:
                    outcome = f"TOOL ERROR ({type(e).__name__}): {e}"
                    log.exception("tool failed agent=%s tool=%s", self.name, tc.name)
                calls.append(ToolCall(tool=tc.name, args=tc.arguments, result=outcome))
                messages.append(ChatMessage(role="tool", content=outcome[:8000],
                                            tool_call_id=tc.id))
        else:
            log.warning("agent %s hit MAX_ROUNDS", self.name)

        AGENT_TURNS.labels(agent=self.name, status=status).inc()
        return AgentResult(
            response=(resp.text if resp and resp.text
                      else "I ran the requested tools but produced no final answer — see the tool results."),
            tool_calls=calls,
            status=status,
            model=resp.model if resp else "",
            fallback_depth=resp.fallback_depth if resp else 0,
        )
