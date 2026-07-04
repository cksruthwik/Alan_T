"""Core domain types. No provider SDK types cross this boundary (ADR-022)."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Literal

Role = Literal["user", "assistant", "system", "tool"]


@dataclass
class ChatMessage:
    role: Role
    content: str


@dataclass
class ChatRequest:
    messages: list[ChatMessage]
    temperature: float | None = None
    max_tokens: int | None = None
    response_format: dict[str, Any] | None = None  # provider-native JSON mode


@dataclass
class ChatResponse:
    text: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    fallback_depth: int = 0  # 0 = primary answered


@dataclass
class ChatDelta:
    text: str


class MessageKind(StrEnum):
    TEXT = "text"
    AUDIO = "audio"  # M6 — raises "not yet" until then (voice-ready contract)
    FILE = "file"


@dataclass
class IncomingMessage:
    kind: MessageKind
    text: str = ""
    file_path: str | None = None
    channel: str = "web"  # web | telegram | voice | api


class AgentStatus(StrEnum):
    OK = "ok"
    DEGRADED = "degraded"
    NEEDS_APPROVAL = "needs_approval"


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]


@dataclass
class ToolCall:
    tool: str
    args: dict[str, Any]
    result: Any = None


@dataclass
class AgentTask:
    message: IncomingMessage
    history: list[ChatMessage] = field(default_factory=list)
    skills: list[str] = field(default_factory=list)  # empty until M3 (SKILLS layer)


@dataclass
class AgentResult:
    response: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    handoff: str | None = None
    status: AgentStatus = AgentStatus.OK
    degraded: list[str] = field(default_factory=list)  # which parts were unavailable
    model: str = ""
    fallback_depth: int = 0


@dataclass
class MemoryFact:
    content: str
    kind: str = "fact"
    noted_at: str = ""  # ISO date, for "noted 2026-05-02: ..." formatting


@dataclass
class Citation:
    vpath: str
    snippet: str = ""
    score: float = 0.0


class HonestFailure(Exception):
    """All providers in a fallback chain are exhausted; user is told honestly."""

    def __init__(self, detail: str, retry_after_seconds: int | None = None):
        super().__init__(detail)
        self.retry_after_seconds = retry_after_seconds
