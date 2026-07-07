"""Reflection engine (Docs_COMPLEX/ai/REFLECTION_ENGINE.md).

Grades a finished task run — verdict + one transferable lesson — on the
REFLECTOR role. A useful lesson is banked to memory (source `reflection`,
per MEMORY_ARCHITECTURE), which is how the system's judgment compounds.
"""

from __future__ import annotations

import json
import logging

from alan_t.core.agents.base import AgentContext
from alan_t.core.types import ChatMessage, ChatRequest

log = logging.getLogger("alan_t.reflection")

_PROMPT = """You are Alan_T's reflection engine. Grade this finished task run.

Goal: {goal}

Plan and outcomes:
{outcomes}

Reply with ONLY this JSON:
{{"verdict": "success" | "partial" | "failure",
  "reasoning": "<one or two sentences>",
  "lesson": "<ONE transferable lesson for future planning, or empty string if none>"}}"""


class ReflectionEngine:
    async def reflect(self, goal: str, plan: list[dict], results: list[dict],
                      ctx: AgentContext) -> dict:
        outcomes = "\n".join(
            f"step {r['step']} [{r['agent']}] → {r['status']}: {r['response'][:300]}"
            for r in results) or "(no steps ran)"
        resp = await ctx.llm.complete("REFLECTOR", ChatRequest(
            messages=[ChatMessage(role="user",
                                  content=_PROMPT.format(goal=goal, outcomes=outcomes))],
            response_format={"type": "json_object"},
        ))
        verdict = json.loads(resp.text)
        lesson = (verdict.get("lesson") or "").strip()
        if lesson and verdict.get("verdict") != "success":
            # bank only lessons from imperfect runs — success needs no correction
            try:
                await ctx.memory.remember(f"Task-planning lesson: {lesson}", kind="lesson",
                                          source="reflection")
            except Exception:
                log.warning("could not store reflection lesson")
        log.info("reflection verdict=%s", verdict.get("verdict"))
        return verdict
