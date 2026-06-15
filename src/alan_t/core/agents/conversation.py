"""Conversation Agent — M0's only agent (BUILD_ORDER.md M0).

General dialogue with follow-up resolution from the session window. Runs on the shared
contract with no Supervisor yet (direct dispatch). Persists the turn and answers via the
CHAT purpose through the model seam.
"""

from __future__ import annotations

import logging

from alan_t.core.agents.base import AgentContext
from alan_t.core.types import (
    AgentResult,
    AgentTask,
    ChatMessage,
    ChatRequest,
    Role,
)

logger = logging.getLogger(__name__)

PERSONA = """You are Alan_T, the user's personal assistant. You have persistent memory \
and access to the user's notes, files, and tools.

Rules that override everything else:
- Never invent facts about the user's documents, schedule, or memory. If you don't know, say so.
- When a task is degraded (a tool or memory was unavailable), say which part.
- Be direct. No filler, no flattery."""


class ConversationAgent:
    name = "conversation"
    description = "General dialogue, follow-ups, and tone. The default agent."

    async def run(self, task: AgentTask, ctx: AgentContext) -> AgentResult:
        if task.message.kind != "text" or not task.message.text:
            # Voice-ready boundary: non-text kinds are not handled until later milestones.
            return AgentResult(
                response="I can only handle text messages right now.",
                status="degraded",
                degraded=[f"unsupported_kind:{task.message.kind}"],
            )

        user_text = task.message.text
        degraded: list[str] = []

        await ctx.store.ensure_session(task.session_id)
        await ctx.store.append_turn(task.session_id, ChatMessage(Role.USER, user_text))

        # Recall long-term memory (keyed by the stable user id, not the session) before the
        # LLM call. Best-effort: a memory backend failure degrades the turn, never fails it.
        memory_snippets: list[str] = []
        if ctx.memory:
            try:
                memory_snippets = await ctx.memory.search(task.user_id, user_text)
            except Exception:
                logger.exception("memory recall failed for user %s", task.user_id)
                degraded.append("memory_recall_unavailable")

        system_content = PERSONA
        if memory_snippets:
            system_content += "\n\n# MEMORY\n" + "\n".join(f"- {m}" for m in memory_snippets)

        history = await ctx.store.recent_turns(task.session_id)
        messages = [ChatMessage(Role.SYSTEM, system_content), *history]

        resp = await ctx.models.complete("CHAT", ChatRequest(messages=messages))

        await ctx.store.append_turn(task.session_id, ChatMessage(Role.ASSISTANT, resp.text))

        # Persist the user's message to long-term memory after the turn. Best-effort, as above.
        if ctx.memory:
            try:
                await ctx.memory.add(task.user_id, user_text)
            except Exception:
                logger.exception("memory write failed for user %s", task.user_id)
                degraded.append("memory_write_unavailable")

        return AgentResult(
            response=resp.text,
            status="degraded" if degraded else "ok",
            model=resp.model,
            degraded=degraded,
            usage=resp.usage,
        )
