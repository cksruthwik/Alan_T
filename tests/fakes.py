"""First-class fakes — the testing API of the system (TEST_STRATEGY.md §2)."""

from __future__ import annotations

from alan_t.core.ports import (
    LLMProvider,
    MemoryPort,
    ModelSpec,
    ProviderUnavailableError,
    RateLimitedError,
)
from alan_t.core.types import ChatMessage, ChatRequest, ChatResponse, Role, Usage


class FakeLLMProvider:
    """Scripted LLM provider. Optionally raise to exercise the fallback chain."""

    def __init__(
        self, reply: str = "hello from fake", fail_providers: set[str] | None = None
    ) -> None:
        self.reply = reply
        self.fail_providers = fail_providers or set()
        self.calls: list[ModelSpec] = []

    async def chat(self, spec: ModelSpec, req: ChatRequest) -> ChatResponse:
        self.calls.append(spec)
        if spec.provider in self.fail_providers:
            raise RateLimitedError(f"{spec.provider} rate-limited (fake)")
        return ChatResponse(text=self.reply, model=spec.litellm_model, usage=Usage(1, 1))


class AlwaysDownProvider:
    async def chat(self, spec: ModelSpec, req: ChatRequest) -> ChatResponse:
        raise ProviderUnavailableError("down (fake)")


class InMemoryConversationStore:
    """In-memory ConversationStore for fast unit tests."""

    def __init__(self) -> None:
        self.sessions: set[str] = set()
        self.turns: dict[str, list[ChatMessage]] = {}

    async def ensure_session(self, session_id: str, channel: str = "api") -> None:
        self.sessions.add(session_id)
        self.turns.setdefault(session_id, [])

    async def append_turn(self, session_id: str, message: ChatMessage) -> None:
        self.turns.setdefault(session_id, []).append(message)

    async def recent_turns(self, session_id: str, limit: int = 20) -> list[ChatMessage]:
        return self.turns.get(session_id, [])[-limit:]


class InMemoryMemoryStore:
    """In-process MemoryPort fake. Stores raw strings; search returns all items."""

    def __init__(self) -> None:
        self.items: dict[str, list[str]] = {}

    async def add(self, user_id: str, content: str) -> None:
        self.items.setdefault(user_id, []).append(content)

    async def search(self, user_id: str, query: str, limit: int = 5) -> list[str]:
        return self.items.get(user_id, [])[-limit:]


class BrokenMemoryStore:
    """MemoryPort that always raises — exercises the agent's best-effort degradation."""

    async def add(self, user_id: str, content: str) -> None:
        raise RuntimeError("memory backend down (fake)")

    async def search(self, user_id: str, query: str, limit: int = 5) -> list[str]:
        raise RuntimeError("memory backend down (fake)")


# Type-checker sanity: the fakes satisfy the ports.
_p: LLMProvider = FakeLLMProvider()
_m: MemoryPort = InMemoryMemoryStore()
_ = Role  # keep import used for downstream test convenience
