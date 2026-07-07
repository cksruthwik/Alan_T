"""Vision agent (Docs_COMPLEX/agents/VISION_AGENT.md): image in → answer out.

VISION role is NVIDIA-primary with Google fallback (config/models.yaml) —
image quota lives on the provider with the most headroom.
"""

from __future__ import annotations

from alan_t.core.agents.base import AgentContext
from alan_t.core.types import (
    AgentResult,
    AgentStatus,
    AgentTask,
    ChatMessage,
    ChatRequest,
    ToolSpec,
)


class VisionAgent:
    name = "vision"
    description = "Analyze an image/photo/screenshot attached to the message (describe, OCR, answer questions)."
    tools: list[ToolSpec] = []

    async def run(self, task: AgentTask, ctx: AgentContext) -> AgentResult:
        if not task.message.file_path:
            return AgentResult(
                response="I was asked to analyze an image but none was attached.",
                status=AgentStatus.DEGRADED, degraded=["vision"],
            )
        resp = await ctx.llm.complete("VISION", ChatRequest(messages=[
            ChatMessage(
                role="user",
                content=task.message.text or "Describe this image in detail.",
                images=[task.message.file_path],
            ),
        ]))
        return AgentResult(response=resp.text, model=resp.model, fallback_depth=resp.fallback_depth)
