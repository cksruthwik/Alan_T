"""Conversation agent (M0): general dialogue with persona + memory injection."""

from __future__ import annotations

from collections.abc import AsyncIterator

from alan_t.core.agents.base import AgentContext
from alan_t.core.prompts import render
from alan_t.core.types import (
    AgentResult,
    AgentStatus,
    AgentTask,
    ChatDelta,
    ChatMessage,
    ChatRequest,
    MessageKind,
    ToolSpec,
)


class ConversationAgent:
    name = "conversation"
    description = "General dialogue, follow-ups, tone. Default agent."
    tools: list[ToolSpec] = []

    async def _assemble(
        self, task: AgentTask, ctx: AgentContext
    ) -> tuple[ChatRequest, list[str]]:
        degraded: list[str] = []
        memory_facts = []
        try:
            if task.message.text:
                memory_facts = await ctx.memory.recall(task.message.text)
        except Exception:
            degraded.append("memory")

        system = render(
            "chat.j2",
            user_name=ctx.user_name,
            features=ctx.config.get("features", {}),
            memory_facts=memory_facts,
            skills=task.skills,
            project_instructions=task.project_instructions,
        )
        messages = [ChatMessage(role="system", content=system)]
        messages += task.history
        messages.append(ChatMessage(role="user", content=task.message.text))
        return ChatRequest(messages=messages), degraded

    async def run(self, task: AgentTask, ctx: AgentContext) -> AgentResult:
        if task.message.kind == MessageKind.AUDIO:
            return AgentResult(
                response="Voice notes aren't supported yet — coming with the voice milestone.",
                status=AgentStatus.DEGRADED,
                degraded=["voice"],
            )
        req, degraded = await self._assemble(task, ctx)
        resp = await ctx.llm.complete("CHAT", req)
        return AgentResult(
            response=resp.text,
            status=AgentStatus.DEGRADED if degraded else AgentStatus.OK,
            degraded=degraded,
            model=resp.model,
            fallback_depth=resp.fallback_depth,
        )

    async def run_stream(self, task: AgentTask, ctx: AgentContext) -> AsyncIterator[ChatDelta]:
        req, _ = await self._assemble(task, ctx)
        async for delta in ctx.llm.stream("CHAT", req):
            yield delta
