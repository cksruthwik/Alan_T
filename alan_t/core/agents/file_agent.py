"""File agent (M2): question → hybrid retrieval → cited answer (KNOWLEDGE.md §4).

Honesty contract: empty retrieval → "didn't find anything", never improvisation;
low-relevance retrieval → uncertainty prefix; degraded pipeline → stated.
"""

from __future__ import annotations

import re

from alan_t.core.agents.base import AgentContext
from alan_t.core.knowledge.retrieval import Retriever
from alan_t.core.prompts import render
from alan_t.core.types import (
    AgentResult,
    AgentStatus,
    AgentTask,
    ChatMessage,
    ChatRequest,
    ToolSpec,
)

_ANAPHORA = re.compile(r"\b(that|this|it|the second one|the first one|them|those)\b", re.I)
LOW_RELEVANCE = 0.35  # best cosine similarity below this → uncertainty prefix


class FileAgent:
    name = "file"
    description = "Search and answer questions over the user's ingested notes/files (RAG)."
    tools: list[ToolSpec] = []

    def __init__(self, retriever: Retriever):
        self._retriever = retriever

    async def _standalone_query(self, task: AgentTask, ctx: AgentContext) -> str:
        q = task.message.text
        if not task.history or not _ANAPHORA.search(q):
            return q  # rewrite only when needed — skipping is the point
        resp = await ctx.llm.complete("SUMMARIZER", ChatRequest(messages=[ChatMessage(
            role="user",
            content=render("query_rewrite.j2", history=task.history[-6:], question=q),
        )]))
        return resp.text.strip() or q

    async def run(self, task: AgentTask, ctx: AgentContext) -> AgentResult:
        query = await self._standalone_query(task, ctx)
        chunks = await self._retriever.search(query)

        if not chunks:
            return AgentResult(
                response=f'I didn\'t find anything about "{query}" in your ingested files.',
                status=AgentStatus.OK,
            )

        system = render("rag_answer.j2", user_name=ctx.user_name, chunks=chunks)
        if task.skills:
            system += "\n\nSelected skills for this turn:\n" + "\n".join(task.skills)
        resp = await ctx.llm.complete("CHAT", ChatRequest(messages=[
            ChatMessage(role="system", content=system),
            ChatMessage(role="user", content=task.message.text),
        ]))

        answer = resp.text
        best_sim = max(c.similarity for c in chunks)
        if best_sim < LOW_RELEVANCE:
            answer = (
                "I'm not confident the files I found are actually about this — "
                f"here's the closest match:\n\n{answer}"
            )
        return AgentResult(
            response=answer,
            status=AgentStatus.OK,
            model=resp.model,
            fallback_depth=resp.fallback_depth,
        )
