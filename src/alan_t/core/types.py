"""Core domain types. Pure data — no provider/framework types cross this line.

These are the types every port and agent speaks. Adapters translate provider SDK
types to/from these at the edge (SYSTEM_OVERVIEW.md layering rules).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Literal


class Role(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"
    TOOL = "tool"


# Voice-ready from M0: the interface boundary models every inbound message as one of
# these kinds. M0 handles `text` and `file`; `audio` is wired at M6 (AGENTS.md §2).
MessageKind = Literal["text", "audio", "file"]


@dataclass(slots=True)
class IncomingMessage:
    """A message arriving at an interface boundary (HTTP, Telegram, …)."""

    kind: MessageKind
    text: str | None = None
    # For `file`/`audio` kinds, a reference the adapter can resolve. Unused at M0 text path.
    ref: str | None = None


@dataclass(slots=True)
class ChatMessage:
    """One turn in a model conversation."""

    role: Role
    content: str


@dataclass(slots=True)
class ChatRequest:
    """Provider-neutral chat request. Adapters map this to LiteLLM kwargs."""

    messages: list[ChatMessage]
    temperature: float | None = None
    max_tokens: int | None = None


@dataclass(slots=True)
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass(slots=True)
class ChatResponse:
    """Provider-neutral chat response."""

    text: str
    model: str
    usage: Usage = field(default_factory=Usage)
    finish_reason: str | None = None


AgentStatus = Literal["ok", "degraded", "needs_approval"]


@dataclass(slots=True)
class AgentTask:
    """A routed instruction for an agent.

    `session_id` scopes the ephemeral conversation window (one chat). `user_id` is the
    stable identity that long-term memory is keyed by — it must survive restarts and span
    every session, which is what makes "it remembers you" work (MEMORY_ARCHITECTURE.md).
    Single-user for now (`user_id` defaults to one identity); M2's Telegram id flows in here.
    `skills` is empty until M3 (skill-ready from M0 — AGENTS.md §2).
    """

    message: IncomingMessage
    session_id: str
    user_id: str = "default"
    skills: list[str] = field(default_factory=list)


@dataclass(slots=True)
class AgentResult:
    """The uniform result every agent returns (AGENTS.md §2)."""

    response: str
    status: AgentStatus = "ok"
    model: str | None = None
    degraded: list[str] = field(default_factory=list)
    usage: Usage = field(default_factory=Usage)
