"""ConversationStore implementation over SQLAlchemy (POSTGRES_SCHEMA.md).

No ORM types leak into core — methods speak core domain types only.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from ulid import ULID

from alan_t.adapters.models import ConversationTurn, Session
from alan_t.core.types import ChatMessage, Role


class SqlConversationStore:
    """Sessions + turns persistence. Source of truth for conversation history."""

    def __init__(self, factory: async_sessionmaker[AsyncSession]) -> None:
        self._factory = factory

    async def ensure_session(self, session_id: str, channel: str = "api") -> None:
        async with self._factory() as db:
            # Idempotent and dialect-agnostic (single-user scale: no contention).
            exists = await db.get(Session, session_id)
            if exists is None:
                db.add(Session(id=session_id, channel=channel))
                await db.commit()

    async def append_turn(self, session_id: str, message: ChatMessage) -> None:
        async with self._factory() as db:
            db.add(
                ConversationTurn(
                    id=str(ULID()),
                    session_id=session_id,
                    role=message.role.value,
                    content=message.content,
                )
            )
            await db.commit()

    async def recent_turns(self, session_id: str, limit: int = 20) -> list[ChatMessage]:
        async with self._factory() as db:
            # Order by id: ULIDs are time-ordered AND unique, so this is deterministic
            # even when same-instant inserts tie on created_at.
            stmt = (
                select(ConversationTurn)
                .where(ConversationTurn.session_id == session_id)
                .order_by(ConversationTurn.id.desc())
                .limit(limit)
            )
            rows = (await db.execute(stmt)).scalars().all()

        # Return oldest → newest for the model.
        return [ChatMessage(Role(r.role), r.content) for r in reversed(rows)]
