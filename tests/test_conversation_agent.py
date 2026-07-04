"""Unit tests with fakes — the fake-provider mode paying rent (TEST_STRATEGY)."""

from collections.abc import AsyncIterator

from alan_t.adapters.null_memory import NullMemory
from alan_t.core.agents.base import AgentContext
from alan_t.core.agents.conversation import ConversationAgent
from alan_t.core.types import (
    AgentStatus,
    AgentTask,
    ChatDelta,
    ChatRequest,
    ChatResponse,
    IncomingMessage,
    MemoryFact,
    MessageKind,
)


class FakeLLM:
    def __init__(self):
        self.last_request: ChatRequest | None = None

    async def complete(self, purpose: str, req: ChatRequest) -> ChatResponse:
        self.last_request = req
        return ChatResponse(text=f"echo: {req.messages[-1].content}", model="fake/model")

    async def stream(self, purpose: str, req: ChatRequest) -> AsyncIterator[ChatDelta]:
        self.last_request = req
        for word in ("hello", " world"):
            yield ChatDelta(text=word)

    async def embed(self, texts):
        return [[0.0] * 4 for _ in texts]


class RememberingMemory(NullMemory):
    async def recall(self, query, limit=10):
        return [MemoryFact(content="prefers TypeScript", kind="preference", noted_at="2026-07-01")]


def make_ctx(llm=None, memory=None):
    return AgentContext(
        llm=llm or FakeLLM(),
        memory=memory or NullMemory(),
        config={"features": {"knowledge": False, "telegram": False}},
        user_name="Tester",
    )


async def test_text_turn_ok():
    agent = ConversationAgent()
    result = await agent.run(
        AgentTask(message=IncomingMessage(kind=MessageKind.TEXT, text="hi")), make_ctx()
    )
    assert result.status == AgentStatus.OK
    assert result.response == "echo: hi"


async def test_persona_and_memory_in_system_prompt():
    llm = FakeLLM()
    agent = ConversationAgent()
    await agent.run(
        AgentTask(message=IncomingMessage(kind=MessageKind.TEXT, text="hi")),
        make_ctx(llm=llm, memory=RememberingMemory()),
    )
    system = llm.last_request.messages[0]
    assert system.role == "system"
    assert "You are Alan_T" in system.content
    assert "prefers TypeScript" in system.content
    assert "(noted 2026-07-01)" in system.content


async def test_audio_is_honestly_declined():
    agent = ConversationAgent()
    result = await agent.run(
        AgentTask(message=IncomingMessage(kind=MessageKind.AUDIO)), make_ctx()
    )
    assert result.status == AgentStatus.DEGRADED
    assert "voice" in result.degraded


async def test_memory_failure_degrades_not_crashes():
    class BrokenMemory(NullMemory):
        async def recall(self, query, limit=10):
            raise RuntimeError("mem0 down")

    agent = ConversationAgent()
    result = await agent.run(
        AgentTask(message=IncomingMessage(kind=MessageKind.TEXT, text="hi")),
        make_ctx(memory=BrokenMemory()),
    )
    assert result.status == AgentStatus.DEGRADED
    assert result.degraded == ["memory"]
    assert result.response == "echo: hi"


async def test_streaming():
    agent = ConversationAgent()
    chunks = [
        d.text
        async for d in agent.run_stream(
            AgentTask(message=IncomingMessage(kind=MessageKind.TEXT, text="hi")), make_ctx()
        )
    ]
    assert "".join(chunks) == "hello world"
