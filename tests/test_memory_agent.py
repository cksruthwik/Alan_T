"""M1 memory integration on the shared contract (BUILD_ORDER.md M1 done-criteria).

The DoD is "restart → it still remembers". A restart means a *new* session (the API
mints a fresh ULID per conversation when none is supplied — see main.py), so these tests
deliberately use different session_ids across turns while keeping the same user_id. Memory
keyed by session would silently fail this; keyed by user_id it works.
"""

from __future__ import annotations

from alan_t.core.agents.base import AgentContext
from alan_t.core.agents.conversation import ConversationAgent
from alan_t.core.llm import ModelRouter, PurposeConfig
from alan_t.core.ports import ModelSpec
from alan_t.core.types import AgentTask, ChatRequest, IncomingMessage
from tests.fakes import (
    BrokenMemoryStore,
    FakeLLMProvider,
    InMemoryConversationStore,
    InMemoryMemoryStore,
)

CHAT = PurposeConfig(primary=ModelSpec("groq", "llama-3.3-70b-versatile"))


class CapturingLLMProvider(FakeLLMProvider):
    """FakeLLMProvider that also records each ChatRequest for prompt inspection."""

    def __init__(self, reply: str = "ok") -> None:
        super().__init__(reply=reply)
        self.requests: list[ChatRequest] = []

    async def chat(self, spec, req):
        self.requests.append(req)
        return await super().chat(spec, req)


def _ctx(memory, provider=None, store=None) -> AgentContext:
    return AgentContext(
        models=ModelRouter(provider or FakeLLMProvider(), {"CHAT": CHAT}),
        store=store or InMemoryConversationStore(),
        memory=memory,
    )


async def test_memory_stored_under_user_not_session() -> None:
    memory = InMemoryMemoryStore()
    ctx = _ctx(memory)

    await ConversationAgent().run(
        AgentTask(
            message=IncomingMessage(kind="text", text="I prefer TypeScript"),
            session_id="session-abc",
            user_id="alice",
        ),
        ctx,
    )

    assert memory.items.get("alice") == ["I prefer TypeScript"]
    assert "session-abc" not in memory.items


async def test_memory_injected_into_prompt() -> None:
    memory = InMemoryMemoryStore()
    await memory.add("alice", "prefers TypeScript")
    provider = CapturingLLMProvider(reply="You prefer TypeScript")

    result = await ConversationAgent().run(
        AgentTask(
            message=IncomingMessage(kind="text", text="what language do I prefer?"),
            session_id="s",
            user_id="alice",
        ),
        _ctx(memory, provider),
    )

    assert result.status == "ok"
    system_msg = provider.requests[0].messages[0]
    assert "TypeScript" in system_msg.content


async def test_dod_remembers_across_restart() -> None:
    """The headline DoD: store a preference, then recall it in a brand-new session."""
    memory = InMemoryMemoryStore()  # the one thing that survives a "restart"
    agent = ConversationAgent()
    user = "alice"

    # Turn 1 — conversation #1.
    await agent.run(
        AgentTask(
            message=IncomingMessage(kind="text", text="I prefer TypeScript"),
            session_id="conversation-1",
            user_id=user,
        ),
        _ctx(memory, FakeLLMProvider(reply="Noted!")),
    )

    # Turn 2 — restart: fresh conversation store, new session id, same user.
    provider = CapturingLLMProvider(reply="You prefer TypeScript")
    result = await agent.run(
        AgentTask(
            message=IncomingMessage(kind="text", text="what language do I prefer?"),
            session_id="conversation-2",
            user_id=user,
        ),
        _ctx(memory, provider, store=InMemoryConversationStore()),
    )

    assert result.status == "ok"
    system_content = provider.requests[0].messages[0].content
    assert "TypeScript" in system_content, f"memory not recalled; system was: {system_content!r}"


async def test_memory_failure_degrades_not_crashes() -> None:
    """A broken memory backend must not fail the turn — the persona promises this."""
    result = await ConversationAgent().run(
        AgentTask(
            message=IncomingMessage(kind="text", text="hello"),
            session_id="s",
            user_id="alice",
        ),
        _ctx(BrokenMemoryStore(), FakeLLMProvider(reply="hi")),
    )

    assert result.response == "hi"
    assert result.status == "degraded"
    assert "memory_recall_unavailable" in result.degraded
    assert "memory_write_unavailable" in result.degraded


async def test_no_memory_port_still_works() -> None:
    """Backward-compatible when memory=None (no degradation reported)."""
    result = await ConversationAgent().run(
        AgentTask(message=IncomingMessage(kind="text", text="hello"), session_id="s"),
        _ctx(memory=None),
    )
    assert result.status == "ok"
    assert result.degraded == []
