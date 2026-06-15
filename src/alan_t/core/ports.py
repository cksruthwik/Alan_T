"""Ports: the interfaces the core depends on. Adapters implement these.

Core code imports only this module's protocols, never a concrete adapter
(SYSTEM_OVERVIEW.md layering rule 1). The lean build defines only the ports M0-M2
actually need; more are added reactively (ADR-022).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from alan_t.core.types import ChatMessage, ChatRequest, ChatResponse


@dataclass(frozen=True, slots=True)
class ModelSpec:
    """A resolved (provider, model, params) target from config."""

    provider: str
    model: str
    temperature: float | None = None
    max_tokens: int | None = None

    @property
    def litellm_model(self) -> str:
        """LiteLLM addresses models as `<provider>/<model>`."""
        return f"{self.provider}/{self.model}"


class RateLimitedError(Exception):
    """Raised by an adapter when a provider rate-limits (HTTP 429)."""


class ProviderUnavailableError(Exception):
    """Raised by an adapter when a provider is unreachable / errors."""


@runtime_checkable
class LLMProvider(Protocol):
    """The one model seam. A single function over every provider (LLM_STRATEGY.md §4)."""

    async def chat(self, spec: ModelSpec, req: ChatRequest) -> ChatResponse: ...


@runtime_checkable
class ConversationStore(Protocol):
    """Persistence for sessions and turns (RelationalStore, M0 slice)."""

    async def ensure_session(self, session_id: str, channel: str = "api") -> None: ...

    async def append_turn(self, session_id: str, message: ChatMessage) -> None: ...

    async def recent_turns(self, session_id: str, limit: int = 20) -> list[ChatMessage]: ...


@runtime_checkable
class MemoryPort(Protocol):
    """Long-term memory seam backed by Mem0 (MEMORY_ARCHITECTURE.md)."""

    async def add(self, user_id: str, content: str) -> None: ...

    async def search(self, user_id: str, query: str, limit: int = 5) -> list[str]: ...
