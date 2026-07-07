"""PersonalStore — contacts, documents, task runs (migration 0002).

Contacts + documents as plain Postgres rows behind async methods, exposed to
agents only as gated tools.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from alan_t.adapters.postgres.models import Contact, Document, TaskRun


class PersonalStore:
    def __init__(self, engine: AsyncEngine):
        self._sessions = async_sessionmaker(engine, expire_on_commit=False)

    # ── contacts ───────────────────────────────────────────────────────

    async def upsert_contact(self, name: str, email: str | None = None,
                             phone: str | None = None, notes: str | None = None) -> dict:
        async with self._sessions.begin() as db:
            existing = await db.scalar(select(Contact).where(Contact.name.ilike(name)))
            if existing:
                existing.email = email or existing.email
                existing.phone = phone or existing.phone
                existing.notes = notes or existing.notes
                c = existing
            else:
                c = Contact(name=name, email=email, phone=phone, notes=notes)
                db.add(c)
            await db.flush()
            return {"id": str(c.id), "name": c.name, "email": c.email, "phone": c.phone}

    async def resolve_contact(self, query: str) -> list[dict]:
        async with self._sessions() as db:
            rows = await db.scalars(select(Contact).where(or_(
                Contact.name.ilike(f"%{query}%"), Contact.email.ilike(f"%{query}%"))).limit(5))
            return [{"id": str(c.id), "name": c.name, "email": c.email,
                     "phone": c.phone, "notes": c.notes} for c in rows]

    # ── documents ──────────────────────────────────────────────────────

    async def create_document(self, title: str, content: str = "",
                              format: str = "markdown") -> dict:
        async with self._sessions.begin() as db:
            d = Document(title=title, content=content, format=format)
            db.add(d)
            await db.flush()
            return {"id": str(d.id), "title": d.title, "version": d.version}

    async def update_document(self, document_id: str, content: str,
                              title: str | None = None) -> dict:
        async with self._sessions.begin() as db:
            d = await db.get(Document, uuid.UUID(document_id))
            if d is None:
                raise KeyError(f"unknown document: {document_id}")
            d.content = content
            d.title = title or d.title
            d.version += 1
            return {"id": str(d.id), "title": d.title, "version": d.version}

    async def get_document(self, document_id: str) -> dict:
        async with self._sessions() as db:
            d = await db.get(Document, uuid.UUID(document_id))
            if d is None:
                raise KeyError(f"unknown document: {document_id}")
            return {"id": str(d.id), "title": d.title, "content": d.content,
                    "format": d.format, "version": d.version}

    async def list_documents(self, limit: int = 20) -> list[dict]:
        async with self._sessions() as db:
            rows = await db.scalars(
                select(Document).order_by(Document.updated_at.desc()).limit(limit))
            return [{"id": str(d.id), "title": d.title, "version": d.version,
                     "updated_at": d.updated_at.isoformat()} for d in rows]

    # ── task runs (planner) ────────────────────────────────────────────

    async def create_task_run(self, goal: str, plan: list[dict]) -> str:
        async with self._sessions.begin() as db:
            t = TaskRun(goal=goal, plan=plan, status="planned")
            db.add(t)
            await db.flush()
            return str(t.id)

    async def finish_task_run(self, task_id: str, status: str,
                              step_results: list[dict], reflection: dict | None) -> None:
        async with self._sessions.begin() as db:
            t = await db.get(TaskRun, uuid.UUID(task_id))
            if t is None:
                return
            t.status = status
            t.step_results = step_results
            t.reflection = reflection
            t.finished_at = datetime.now(timezone.utc)

    async def get_task_run(self, task_id: str) -> dict | None:
        async with self._sessions() as db:
            t = await db.get(TaskRun, uuid.UUID(task_id))
            if t is None:
                return None
            return {"id": str(t.id), "goal": t.goal, "plan": t.plan, "status": t.status,
                    "step_results": t.step_results, "reflection": t.reflection,
                    "created_at": t.created_at.isoformat()}

    async def list_task_runs(self, limit: int = 20) -> list[dict]:
        async with self._sessions() as db:
            rows = await db.scalars(
                select(TaskRun).order_by(TaskRun.created_at.desc()).limit(limit))
            return [{"id": str(t.id), "goal": t.goal, "status": t.status,
                     "created_at": t.created_at.isoformat()} for t in rows]
