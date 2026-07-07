"""Supervisor (M3, Docs_COMPLEX/agents/SUPERVISOR_AGENT.md): one ROUTER-model
call selects the agent AND the relevant skill(s) from the progressive-disclosure
menus. Falls back to the pre-M3 heuristic if the model call or parse fails —
routing must never take the system down.
"""

from __future__ import annotations

import json
import logging
import re

from alan_t.core.agents.base import Agent, AgentContext
from alan_t.core.skills import SkillLibrary
from alan_t.core.types import AgentTask, ChatMessage, ChatRequest, MessageKind

log = logging.getLogger("alan_t.supervisor")

_FILE_HINT = re.compile(r"\b(my notes?|my files?|my docs?|in the notes|in my|according to)\b", re.I)

_PROMPT = """You route a personal assistant's incoming message to exactly one agent, \
and select any skills that clearly apply (usually none).

Agents:
{agents}

Skills (select only on a clear match — a weak match means select none):
{skills}

Reply with ONLY this JSON: {{"agent": "<name>", "skills": ["<name>", ...]}}"""


class Supervisor:
    def __init__(self, agents: dict[str, Agent], skills: SkillLibrary,
                 default: str = "conversation", use_llm: bool = True):
        self._agents = agents
        self._skills = skills
        self._default = default
        self._use_llm = use_llm  # features.supervisor=false → heuristic-only routing
        self._menu = "\n".join(f"- {name}: {a.description}" for name, a in agents.items())

    def _heuristic(self, task: AgentTask) -> tuple[str, list[str]]:
        if task.message.kind == MessageKind.FILE and "vision" in self._agents:
            return "vision", []
        if "file" in self._agents and _FILE_HINT.search(task.message.text or ""):
            return "file", []
        return self._default, []

    async def route(self, task: AgentTask, ctx: AgentContext) -> tuple[Agent, list[str]]:
        """→ (agent, selected skill names). Skill bodies are injected by the caller."""
        name, skill_names = self._heuristic(task)
        if not self._use_llm:
            return self._agents[name], skill_names
        try:
            resp = await ctx.llm.complete("ROUTER", ChatRequest(
                messages=[
                    ChatMessage(role="system", content=_PROMPT.format(
                        agents=self._menu, skills=self._skills.menu() or "(none)")),
                    ChatMessage(role="user", content=task.message.text or f"[{task.message.kind}]"),
                ],
                response_format={"type": "json_object"},
            ))
            decision = json.loads(resp.text)
            if decision.get("agent") in self._agents:
                name = decision["agent"]
            skill_names = [s for s in decision.get("skills", []) if self._skills.get(s)]
        except Exception as e:  # routing must degrade to the heuristic, never crash a turn
            log.warning("router fallback to heuristic: %s", type(e).__name__)
        log.info("routed agent=%s skills=%s", name, skill_names)
        return self._agents[name], skill_names
