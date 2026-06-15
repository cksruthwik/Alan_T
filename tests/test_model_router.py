"""ModelRouter: fallback chain + exhaustion (LLM_STRATEGY.md §4)."""

from __future__ import annotations

import pytest

from alan_t.core.llm import AllProvidersExhaustedError, ModelRouter, PurposeConfig
from alan_t.core.ports import ModelSpec
from alan_t.core.types import ChatMessage, ChatRequest, Role
from tests.fakes import AlwaysDownProvider, FakeLLMProvider

CHAT = PurposeConfig(
    primary=ModelSpec("groq", "llama-3.3-70b-versatile"),
    fallbacks=(
        ModelSpec("gemini", "gemini-2.5-flash"),
        ModelSpec("nvidia_nim", "deepseek-ai/deepseek-r1"),
    ),
)


def _req() -> ChatRequest:
    return ChatRequest(messages=[ChatMessage(Role.USER, "hi")])


async def test_uses_primary_when_healthy() -> None:
    provider = FakeLLMProvider(reply="ok")
    router = ModelRouter(provider, {"CHAT": CHAT})

    resp = await router.complete("CHAT", _req())

    assert resp.text == "ok"
    assert [c.provider for c in provider.calls] == ["groq"]


async def test_falls_through_to_next_provider() -> None:
    provider = FakeLLMProvider(reply="from gemini", fail_providers={"groq"})
    router = ModelRouter(provider, {"CHAT": CHAT})

    resp = await router.complete("CHAT", _req())

    assert resp.text == "from gemini"
    assert [c.provider for c in provider.calls] == ["groq", "gemini"]


async def test_raises_when_all_exhausted() -> None:
    router = ModelRouter(AlwaysDownProvider(), {"CHAT": CHAT})

    with pytest.raises(AllProvidersExhaustedError):
        await router.complete("CHAT", _req())


async def test_unknown_purpose_raises() -> None:
    router = ModelRouter(FakeLLMProvider(), {"CHAT": CHAT})

    with pytest.raises(KeyError):
        await router.complete("REASONER", _req())
