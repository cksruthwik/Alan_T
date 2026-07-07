"""Task planning engine (Docs_COMPLEX/ai/PLANNING_ENGINE.md).

Goal → REASONER decomposes into a bounded, validated step list → steps execute
sequentially through the normal agents (same contract, same permission gate —
a plan step can do nothing a chat turn couldn't) → outcomes recorded →
reflection engine grades the run and banks the lesson.

Validation is the anti-fabrication line: a plan naming an unknown agent is
rejected before anything runs, like the doc's plan validator demands.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from alan_t.core.agents.base import Agent, AgentContext
from alan_t.core.observability import TASK_RUNS
from alan_t.core.types import AgentTask, ChatMessage, ChatRequest, IncomingMessage, MessageKind

log = logging.getLogger("alan_t.planner")

MAX_STEPS = 8

_PLAN_PROMPT = """You are Alan_T's task planner. Decompose the user's goal into at most {max_steps} \
sequential steps. Each step is executed by exactly one agent from this roster:

{agents}

Reply with ONLY this JSON:
{{"steps": [{{"agent": "<name>", "instruction": "<what that agent should do, self-contained>"}}]}}

Rules: fewest steps that achieve the goal; every instruction must be executable by its
agent's described capabilities; never invent agents not on the roster."""


class TaskPlanner:
    def __init__(self, agents: dict[str, Agent], store):
        self._agents = agents
        self._store = store  # PersonalStore
        self._menu = "\n".join(f"- {n}: {a.description}" for n, a in agents.items())

    async def plan(self, goal: str, ctx: AgentContext) -> list[dict[str, str]]:
        resp = await ctx.llm.complete("REASONER", ChatRequest(
            messages=[
                ChatMessage(role="system",
                            content=_PLAN_PROMPT.format(max_steps=MAX_STEPS, agents=self._menu)),
                ChatMessage(role="user", content=goal),
            ],
            response_format={"type": "json_object"},
        ))
        steps = json.loads(resp.text).get("steps", [])[:MAX_STEPS]
        bad = [s.get("agent") for s in steps if s.get("agent") not in self._agents]
        if bad:
            raise ValueError(f"plan names unknown agents: {bad} — rejected, nothing ran")
        if not steps:
            raise ValueError("planner produced an empty plan")
        return [{"agent": s["agent"], "instruction": s["instruction"]} for s in steps]

    async def run(self, goal: str, ctx: AgentContext, reflector=None) -> dict[str, Any]:
        """Plan + execute + reflect. Returns the full task-run record."""
        steps = await self.plan(goal, ctx)
        task_id = await self._store.create_task_run(goal, steps)
        log.info("task %s: %d steps for goal %r", task_id, len(steps), goal[:80])

        results: list[dict] = []
        status = "succeeded"
        context_note = ""
        for i, step in enumerate(steps, 1):
            agent = self._agents[step["agent"]]
            instruction = step["instruction"]
            if context_note:
                instruction += f"\n\n(Context from earlier steps: {context_note[:2000]})"
            try:
                result = await agent.run(AgentTask(message=IncomingMessage(
                    kind=MessageKind.TEXT, text=instruction, channel="planner")), ctx)
                results.append({"step": i, "agent": agent.name, "status": str(result.status),
                                "response": result.response[:4000]})
                context_note += f"\nstep {i} ({agent.name}): {result.response[:500]}"
                if str(result.status) == "needs_approval":
                    status = "waiting_approval"
                    break  # don't run past a step that's blocked on the user
            except Exception as e:
                log.exception("task %s step %d failed", task_id, i)
                results.append({"step": i, "agent": agent.name, "status": "error",
                                "response": f"{type(e).__name__}: {e}"})
                status = "failed"
                break

        reflection = None
        if reflector is not None:
            try:
                reflection = await reflector.reflect(goal, steps, results, ctx)
            except Exception:
                log.exception("reflection failed for task %s", task_id)

        await self._store.finish_task_run(task_id, status, results, reflection)
        TASK_RUNS.labels(outcome=status).inc()
        return {"task_id": task_id, "goal": goal, "status": status,
                "steps": results, "reflection": reflection}
