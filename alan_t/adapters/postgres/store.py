"""Conversation persistence over async SQLAlchemy: sessions, turns, projects."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from alan_t.adapters.postgres.models import ConversationTurn, Project, Session
from alan_t.core.types import ChatMessage


def make_engine(database_url: str) -> AsyncEngine:
    return create_async_engine(database_url, pool_pre_ping=True)


class ConversationStore:
    def __init__(self, engine: AsyncEngine):
        self._sessions = async_sessionmaker(engine, expire_on_commit=False)

    async def create_session(self, channel: str = "web", title: str | None = None,
                             project_id: uuid.UUID | None = None) -> uuid.UUID:
        async with self._sessions.begin() as db:
            s = Session(channel=channel, title=title, project_id=project_id)
            db.add(s)
            await db.flush()
            return s.id

    async def list_sessions(self, archived: bool = False, project_id: uuid.UUID | None = None,
                            limit: int = 200) -> list[Session]:
        """Newest activity first (ChatGPT ordering), active by default."""
        q = select(Session).where(
            Session.archived_at.isnot(None) if archived else Session.archived_at.is_(None))
        if project_id is not None:
            q = q.where(Session.project_id == project_id)
        q = q.order_by(func.coalesce(Session.last_message_at, Session.created_at).desc()).limit(limit)
        async with self._sessions() as db:
            return list(await db.scalars(q))

    async def get_session(self, session_id: uuid.UUID) -> Session | None:
        async with self._sessions() as db:
            return await db.get(Session, session_id)

    async def session_exists(self, session_id: uuid.UUID) -> bool:
        return await self.get_session(session_id) is not None

    async def update_session(self, session_id: uuid.UUID, *, title: str | None = None,
                             project_id: uuid.UUID | str | None = "unset",
                             archived: bool | None = None) -> bool:
        async with self._sessions.begin() as db:
            s = await db.get(Session, session_id)
            if s is None:
                return False
            if title is not None:
                s.title = title
            if project_id != "unset":
                s.project_id = project_id
            if archived is not None:
                s.archived_at = datetime.now(timezone.utc) if archived else None
            return True

    async def delete_session(self, session_id: uuid.UUID) -> bool:
        """Hard delete: the user owns this data, delete means delete."""
        async with self._sessions.begin() as db:
            s = await db.get(Session, session_id)
            if s is None:
                return False
            await db.execute(delete(ConversationTurn)
                             .where(ConversationTurn.session_id == session_id))
            await db.delete(s)
            return True

    # ── projects (ChatGPT-style grouping + shared instructions) ────────

    async def create_project(self, name: str, instructions: str = "") -> uuid.UUID:
        async with self._sessions.begin() as db:
            existing = await db.scalar(select(Project).where(Project.name.ilike(name)))
            if existing:
                if instructions:
                    existing.instructions = instructions
                return existing.id
            p = Project(name=name, instructions=instructions)
            db.add(p)
            await db.flush()
            return p.id

    async def list_projects(self) -> list[dict]:
        async with self._sessions() as db:
            rows = list(await db.scalars(select(Project).order_by(Project.name)))
            counts = dict((await db.execute(
                select(Session.project_id, func.count()).where(Session.project_id.isnot(None))
                .group_by(Session.project_id))).all())
            return [{"id": str(p.id), "name": p.name, "instructions": p.instructions,
                     "chats": counts.get(p.id, 0)} for p in rows]

    async def get_project(self, project_id: uuid.UUID) -> Project | None:
        async with self._sessions() as db:
            return await db.get(Project, project_id)

    async def find_project(self, name: str) -> Project | None:
        async with self._sessions() as db:
            return await db.scalar(select(Project).where(Project.name.ilike(name)))

    async def delete_project(self, project_id: uuid.UUID) -> bool:
        """Chats survive — they just leave the project (ChatGPT semantics)."""
        async with self._sessions.begin() as db:
            p = await db.get(Project, project_id)
            if p is None:
                return False
            for s in await db.scalars(select(Session).where(Session.project_id == project_id)):
                s.project_id = None
            await db.delete(p)
            return True

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
            s = await db.get(Session, session_id)
            if s is not None:
                s.last_message_at = datetime.now(timezone.utc)
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

    async def recent_turns(self, hours: int = 24, limit: int = 200) -> list[ConversationTurn]:
        """User/assistant turns across all sessions in the window (consolidation feed)."""
        from datetime import datetime, timedelta, timezone

        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        async with self._sessions() as db:
            rows = await db.scalars(
                select(ConversationTurn)
                .where(ConversationTurn.created_at >= cutoff,
                       ConversationTurn.role.in_(["user", "assistant"]))
                .order_by(ConversationTurn.created_at)
                .limit(limit)
            )
            return list(rows)

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
