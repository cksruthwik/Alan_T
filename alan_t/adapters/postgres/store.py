"""Conversation persistence over async SQLAlchemy."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from alan_t.adapters.postgres.models import ConversationTurn, Session
from alan_t.core.types import ChatMessage


def make_engine(database_url: str) -> AsyncEngine:
    return create_async_engine(database_url, pool_pre_ping=True)


class ConversationStore:
    def __init__(self, engine: AsyncEngine):
        self._sessions = async_sessionmaker(engine, expire_on_commit=False)

    async def create_session(self, channel: str = "web", title: str | None = None) -> uuid.UUID:
        async with self._sessions.begin() as db:
            s = Session(channel=channel, title=title)
            db.add(s)
            await db.flush()
            return s.id

    async def list_sessions(self) -> list[Session]:
        async with self._sessions() as db:
            rows = await db.scalars(
                select(Session).where(Session.archived_at.is_(None)).order_by(Session.created_at.desc())
            )
            return list(rows)

    async def session_exists(self, session_id: uuid.UUID) -> bool:
        async with self._sessions() as db:
            return await db.get(Session, session_id) is not None

    async def add_turn(
        self,
        session_id: uuid.UUID,
        role: str,
        content: str,
        *,
        agent: str | None = None,
        trace_id: str | None = None,
        token_usage: dict | None = None,
        modality: str = "text",
    ) -> uuid.UUID:
        async with self._sessions.begin() as db:
            t = ConversationTurn(
                session_id=session_id,
                role=role,
                content=content,
                agent=agent,
                trace_id=trace_id,
                token_usage=token_usage,
                modality=modality,
            )
            db.add(t)
            await db.flush()
            return t.id

    async def history(self, session_id: uuid.UUID, limit: int = 40) -> list[ChatMessage]:
        """Recent session window, oldest-first, user/assistant turns only."""
        async with self._sessions() as db:
            rows = await db.scalars(
                select(ConversationTurn)
                .where(
                    ConversationTurn.session_id == session_id,
                    ConversationTurn.role.in_(["user", "assistant"]),
                )
                .order_by(ConversationTurn.created_at.desc())
                .limit(limit)
            )
            turns = list(rows)[::-1]
            return [ChatMessage(role=t.role, content=t.content) for t in turns]

    async def turns(self, session_id: uuid.UUID, limit: int = 100, offset: int = 0) -> list[ConversationTurn]:
        async with self._sessions() as db:
            rows = await db.scalars(
                select(ConversationTurn)
                .where(ConversationTurn.session_id == session_id)
                .order_by(ConversationTurn.created_at)
                .limit(limit)
                .offset(offset)
            )
            return list(rows)
