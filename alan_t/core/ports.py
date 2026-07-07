"""Ports the core depends on. Adapters implement these; wired in app/bootstrap.py.

Lean set per ADR-022 — more ports are added the first time something is swapped.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol

from alan_t.core.types import ChatDelta, ChatRequest, ChatResponse, MemoryFact


class LLMSeam(Protocol):
    """The one seam every model call goes through (LLM_STRATEGY §4)."""

    async def complete(self, purpose: str, req: ChatRequest) -> ChatResponse: ...
    def stream(self, purpose: str, req: ChatRequest) -> AsyncIterator[ChatDelta]: ...
    async def embed(self, texts: list[str]) -> list[list[float]]: ...
    async def transcribe(self, audio_path: str) -> str: ...


class MemoryStore(Protocol):
    """Long-term memory (Mem0 at M1; null object at M0)."""

    async def recall(self, query: str, limit: int = 10) -> list[MemoryFact]: ...
    async def remember(self, content: str, kind: str = "fact", source: str = "explicit") -> None: ...
    async def extract_from_turn(self, user_text: str, assistant_text: str) -> None: ...
