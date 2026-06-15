"""SqlConversationStore against SQLite (contract-ish; real Postgres in CI later)."""

from __future__ import annotations

import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine

from alan_t.adapters.db import Base, make_session_factory
from alan_t.adapters.repository import SqlConversationStore
from alan_t.core.types import ChatMessage, Role


@pytest_asyncio.fixture
async def store() -> SqlConversationStore:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return SqlConversationStore(make_session_factory(engine))


async def test_ensure_session_is_idempotent(store: SqlConversationStore) -> None:
    await store.ensure_session("s1")
    await store.ensure_session("s1")  # must not raise / duplicate
    await store.append_turn("s1", ChatMessage(Role.USER, "hi"))
    turns = await store.recent_turns("s1")
    assert [t.content for t in turns] == ["hi"]


async def test_turns_returned_oldest_to_newest(store: SqlConversationStore) -> None:
    await store.ensure_session("s2")
    for text in ["one", "two", "three"]:
        await store.append_turn("s2", ChatMessage(Role.USER, text))

    turns = await store.recent_turns("s2", limit=2)
    # most recent two, oldest-first
    assert [t.content for t in turns] == ["two", "three"]
