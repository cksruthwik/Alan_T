"""The shared Agent contract (Docs/architecture/AGENTS.md §2) — the one early investment."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from alan_t.core.ports import LLMSeam, MemoryStore
from alan_t.core.types import AgentResult, AgentTask, ToolSpec


@dataclass
class AgentContext:
    """Injected shared services. Agents never construct adapters.

    tools + skills form the Shared Resource Layer (ADR-019): every agent can
    read skills and call gated tools directly — access fans out, authority
    stays at the one permission gate in ToolRegistry.execute.
    """

    llm: LLMSeam
    memory: MemoryStore
    files: Any = None  # FileSource, arrives at M2
    config: dict[str, Any] = field(default_factory=dict)
    user_name: str = "you"
    tools: Any = None  # ToolRegistry
    skills: Any = None  # SkillLibrary
    approvals: Any = None  # ApprovalBroker — ASK-tier calls become pending approvals


class Agent(Protocol):
    name: str
    description: str  # used by the Supervisor for routing (M3)
    tools: list[ToolSpec]

    async def run(self, task: AgentTask, ctx: AgentContext) -> AgentResult: ...
