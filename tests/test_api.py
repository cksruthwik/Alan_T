"""HTTP /chat + auth (API_SPECIFICATION.md). Uses fakes via an injected container."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from alan_t.app.bootstrap import Container
from alan_t.app.config import Settings
from alan_t.app.main import create_app
from alan_t.core.agents.conversation import ConversationAgent
from alan_t.core.llm import ModelRouter, PurposeConfig
from alan_t.core.ports import ModelSpec
from tests.fakes import FakeLLMProvider, InMemoryConversationStore

TOKEN = "test-token"


def _client(reply: str = "pong") -> TestClient:
    settings = Settings(alan_api_token=TOKEN)
    router = ModelRouter(
        FakeLLMProvider(reply=reply),
        {"CHAT": PurposeConfig(primary=ModelSpec("groq", "llama-3.3-70b-versatile"))},
    )
    container = Container(
        settings=settings,
        models=router,
        store=InMemoryConversationStore(),
        conversation=ConversationAgent(),
        memory=None,
    )
    return TestClient(create_app(container))


def test_health_needs_no_auth() -> None:
    resp = _client().get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_chat_rejects_missing_token() -> None:
    resp = _client().post("/chat", json={"message": "hi"})
    assert resp.status_code == 401


def test_chat_happy_path() -> None:
    resp = _client(reply="hello!").post(
        "/chat",
        json={"message": "hi"},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["response"] == "hello!"
    assert body["status"] == "ok"
    assert body["session_id"]


def test_chat_keeps_session_id() -> None:
    client = _client()
    headers = {"Authorization": f"Bearer {TOKEN}"}
    first = client.post("/chat", json={"message": "hi"}, headers=headers).json()
    second = client.post(
        "/chat", json={"message": "again", "session_id": first["session_id"]}, headers=headers
    ).json()
    assert second["session_id"] == first["session_id"]


@pytest.mark.parametrize("payload", [{}, {"message": ""}])
def test_chat_validates_body(payload: dict) -> None:
    resp = _client().post(
        "/chat", json=payload, headers={"Authorization": f"Bearer {TOKEN}"}
    )
    assert resp.status_code == 422
