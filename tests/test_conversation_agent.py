"""Conversation Agent on the shared contract (M0 done-criteria)."""

from __future__ import annotations

from alan_t.core.agents.base import AgentContext
from alan_t.core.agents.conversation import ConversationAgent
from alan_t.core.llm import ModelRouter, PurposeConfig
from alan_t.core.ports import ModelSpec
from alan_t.core.types import AgentTask, IncomingMessage
from tests.fakes import FakeLLMProvider, InMemoryConversationStore

CHAT = PurposeConfig(primary=ModelSpec("groq", "llama-3.3-70b-versatile"))


def _ctx(reply: str = "hi there") -> tuple[AgentContext, InMemoryConversationStore]:
    store = InMemoryConversationStore()
    router = ModelRouter(FakeLLMProvider(reply=reply), {"CHAT": CHAT})
    return AgentContext(models=router, store=store), store


async def test_answers_and_persists_both_turns() -> None:
    ctx, store = _ctx(reply="I'm Alan_T")
    task = AgentTask(message=IncomingMessage(kind="text", text="who are you?"), session_id="s1")

    result = await ConversationAgent().run(task, ctx)

    assert result.status == "ok"
    assert result.response == "I'm Alan_T"
    # user + assistant turns persisted.
    assert [m.content for m in store.turns["s1"]] == ["who are you?", "I'm Alan_T"]


async def test_non_text_kind_is_degraded_not_crash() -> None:
    ctx, _ = _ctx()
    task = AgentTask(message=IncomingMessage(kind="audio", ref="blob://1"), session_id="s2")

    result = await ConversationAgent().run(task, ctx)

    assert result.status == "degraded"
    assert "unsupported_kind:audio" in result.degraded


async def test_history_is_included_across_turns() -> None:
    ctx, store = _ctx(reply="ok")
    agent = ConversationAgent()

    await agent.run(
        AgentTask(message=IncomingMessage(kind="text", text="first"), session_id="s3"), ctx
    )
    await agent.run(
        AgentTask(message=IncomingMessage(kind="text", text="second"), session_id="s3"), ctx
    )

    # 2 user + 2 assistant turns recorded in order.
    assert [m.content for m in store.turns["s3"]] == ["first", "ok", "second", "ok"]
