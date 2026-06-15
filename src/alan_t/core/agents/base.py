"""The shared Agent contract - the one early investment (AGENTS.md §2).

Get this right at agent #1 and agents #4-#10 are mostly "new prompt + new tools".
`AgentContext` carries the shared services every agent reaches: the model seam,
the conversation store, and an injected SKILLS layer (empty until M3).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from alan_t.core.llm import ModelRouter
from alan_t.core.ports import ConversationStore, MemoryPort
from alan_t.core.types import AgentResult, AgentTask


@dataclass(slots=True)
class AgentContext:
    """Shared services injected into every agent run. Agents never build adapters."""

    models: ModelRouter
    store: ConversationStore
    # Bodies of skills the Supervisor selected this turn. Empty until M3 (skill-ready now).
    skills: list[str] = field(default_factory=list)
    # Long-term memory seam (Mem0). None until M1 wires it in; agents guard with `if ctx.memory`.
    memory: MemoryPort | None = None


@runtime_checkable
class Agent(Protocol):
    """Every agent implements this uniform interface."""

    name: str
    description: str  # used by the Supervisor for routing (from M3)

    async def run(self, task: AgentTask, ctx: AgentContext) -> AgentResult: ...
