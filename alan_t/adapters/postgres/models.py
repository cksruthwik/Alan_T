"""SQLAlchemy models — normative shape in Docs/data/POSTGRES_SCHEMA.md.

Alembic migrations are the executable truth; divergence from the doc is a doc bug.
EMBED_DIM=1536 (not the doc's 3072): pgvector HNSW indexes cap at 2000 dims, so we
use gemini-embedding-001 with MRL truncation to 1536 (config/models.yaml EMBEDDER).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    REAL,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from uuid_utils.compat import uuid7

EMBED_DIM = 1536


class Base(DeclarativeBase):
    type_annotation_map = {dict: JSONB, datetime: DateTime(timezone=True)}


def _uuid7() -> uuid.UUID:
    return uuid7()


class Project(Base):
    """ChatGPT-style project: groups sessions, carries shared instructions."""

    __tablename__ = "projects"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid7)
    name: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    instructions: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())


class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid7)
    title: Mapped[str | None] = mapped_column(Text)
    channel: Mapped[str] = mapped_column(Text, nullable=False, default="web")
    project_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("projects.id"))
    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())
    last_message_at: Mapped[datetime | None]
    archived_at: Mapped[datetime | None]


class ConversationTurn(Base):
    __tablename__ = "conversation_turns"
    __table_args__ = (
        CheckConstraint("role IN ('user','assistant','system','tool')", name="role_check"),
        Index("ix_turns_session_created", "session_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid7)
    session_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sessions.id"), nullable=False)
    role: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    modality: Mapped[str] = mapped_column(Text, nullable=False, default="text")
    agent: Mapped[str | None] = mapped_column(Text)
    trace_id: Mapped[str | None] = mapped_column(Text)
    token_usage: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())


class MemoryItem(Base):
    __tablename__ = "memory_items"
    __table_args__ = (
        CheckConstraint("confidence BETWEEN 0 AND 1", name="confidence_check"),
        Index("ix_memory_status_kind", "status", "kind"),
        Index("ix_memory_tags", "tags", postgresql_using="gin"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid7)
    kind: Mapped[str] = mapped_column(Text, nullable=False)      # preference|fact|goal|project|episode|lesson
    content: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False)    # explicit|extracted|consolidated|reflection
    confidence: Mapped[float] = mapped_column(REAL, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="active")
    superseded_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("memory_items.id"))
    origin_ref: Mapped[dict | None] = mapped_column(JSONB)
    tags: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        nullable=False, server_default=func.now(), onupdate=func.now()
    )
    last_accessed_at: Mapped[datetime | None]
    access_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    delete_after: Mapped[datetime | None]
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBED_DIM))


class IngestLedger(Base):
    __tablename__ = "ingest_ledger"

    vpath: Mapped[str] = mapped_column(Text, primary_key=True)
    content_hash: Mapped[str] = mapped_column(Text, nullable=False)
    embedder_model: Mapped[str] = mapped_column(Text, nullable=False)
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(Text, nullable=False)  # ok|failed|pending|tombstoned
    error: Mapped[str | None] = mapped_column(Text)
    embedded_at: Mapped[datetime | None]
    updated_at: Mapped[datetime] = mapped_column(
        nullable=False, server_default=func.now(), onupdate=func.now()
    )


class EmbeddingCache(Base):
    __tablename__ = "embedding_cache"

    content_hash: Mapped[str] = mapped_column(Text, primary_key=True)
    embedder_model: Mapped[str] = mapped_column(Text, primary_key=True)
    vector: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)  # packed float32; never searched
    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())


class Chunk(Base):
    __tablename__ = "chunks"
    __table_args__ = (
        Index("ix_chunks_vpath", "vpath"),
        Index(
            "ix_chunks_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
        # tsv column + GIN index are raw-SQL in the migration (generated column)
    )

    chunk_id: Mapped[str] = mapped_column(Text, primary_key=True)
    vpath: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBED_DIM), nullable=False)


class Contact(Base):
    """Contacts: the assistant's Postgres-backed address book."""

    __tablename__ = "contacts"
    __table_args__ = (Index("ix_contacts_name", "name"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid7)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    email: Mapped[str | None] = mapped_column(Text)
    phone: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        nullable=False, server_default=func.now(), onupdate=func.now()
    )


class Document(Base):
    """AI-editable writing documents, versioned in Postgres."""

    __tablename__ = "documents"
    __table_args__ = (Index("ix_documents_updated", "updated_at"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid7)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    format: Mapped[str] = mapped_column(Text, nullable=False, default="markdown")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        nullable=False, server_default=func.now(), onupdate=func.now()
    )


class TaskRun(Base):
    """Planner task runs (PLANNING_ENGINE.md): goal → plan steps → outcomes → reflection."""

    __tablename__ = "task_runs"
    __table_args__ = (Index("ix_task_runs_created", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid7)
    goal: Mapped[str] = mapped_column(Text, nullable=False)
    plan: Mapped[dict] = mapped_column(JSONB, nullable=False)          # [{agent, instruction}]
    step_results: Mapped[dict | None] = mapped_column(JSONB)           # [{step, response, status}]
    status: Mapped[str] = mapped_column(Text, nullable=False, default="planned")
    reflection: Mapped[dict | None] = mapped_column(JSONB)             # verdict + lesson
    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())
    finished_at: Mapped[datetime | None]


class ToolAudit(Base):
    __tablename__ = "tool_audit"
    __table_args__ = (
        Index("ix_audit_created", "created_at"),
        Index("ix_audit_tool_created", "tool", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid7)
    tool: Mapped[str] = mapped_column(Text, nullable=False)
    agent: Mapped[str] = mapped_column(Text, nullable=False)
    tier: Mapped[str] = mapped_column(Text, nullable=False)
    args_hash: Mapped[str] = mapped_column(Text, nullable=False)
    args_preview: Mapped[str | None] = mapped_column(Text)
    decision: Mapped[str] = mapped_column(Text, nullable=False)
    outcome: Mapped[str] = mapped_column(Text, nullable=False)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    trace_id: Mapped[str | None] = mapped_column(Text)
    session_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())
