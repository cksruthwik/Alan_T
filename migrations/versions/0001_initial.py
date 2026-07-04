"""initial schema — Docs/data/POSTGRES_SCHEMA.md (EMBED_DIM=1536, see models.py)

Revision ID: 0001
Revises:
Create Date: 2026-07-02

"""
import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

DIM = 1536


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "sessions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("title", sa.Text),
        sa.Column("channel", sa.Text, nullable=False, server_default="web"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("archived_at", sa.DateTime(timezone=True)),
    )

    op.create_table(
        "conversation_turns",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("session_id", UUID(as_uuid=True), sa.ForeignKey("sessions.id"), nullable=False),
        sa.Column("role", sa.Text, nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("modality", sa.Text, nullable=False, server_default="text"),
        sa.Column("agent", sa.Text),
        sa.Column("trace_id", sa.Text),
        sa.Column("token_usage", JSONB),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("role IN ('user','assistant','system','tool')", name="role_check"),
    )
    op.create_index("ix_turns_session_created", "conversation_turns", ["session_id", "created_at"])

    op.create_table(
        "memory_items",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("kind", sa.Text, nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("source", sa.Text, nullable=False),
        sa.Column("confidence", sa.REAL, nullable=False),
        sa.Column("status", sa.Text, nullable=False, server_default="active"),
        sa.Column("superseded_by", UUID(as_uuid=True), sa.ForeignKey("memory_items.id")),
        sa.Column("origin_ref", JSONB),
        sa.Column("tags", ARRAY(sa.Text), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("last_accessed_at", sa.DateTime(timezone=True)),
        sa.Column("access_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("delete_after", sa.DateTime(timezone=True)),
        sa.Column("embedding", Vector(DIM)),
        sa.CheckConstraint("confidence BETWEEN 0 AND 1", name="confidence_check"),
    )
    op.create_index("ix_memory_status_kind", "memory_items", ["status", "kind"])
    op.create_index("ix_memory_tags", "memory_items", ["tags"], postgresql_using="gin")

    op.create_table(
        "ingest_ledger",
        sa.Column("vpath", sa.Text, primary_key=True),
        sa.Column("content_hash", sa.Text, nullable=False),
        sa.Column("embedder_model", sa.Text, nullable=False),
        sa.Column("chunk_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("status", sa.Text, nullable=False),
        sa.Column("error", sa.Text),
        sa.Column("embedded_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "embedding_cache",
        sa.Column("content_hash", sa.Text, primary_key=True),
        sa.Column("embedder_model", sa.Text, primary_key=True),
        sa.Column("vector", sa.LargeBinary, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "chunks",
        sa.Column("chunk_id", sa.Text, primary_key=True),
        sa.Column("vpath", sa.Text, nullable=False),
        sa.Column("body", sa.Text, nullable=False),
        sa.Column("payload", JSONB, nullable=False),
        sa.Column("embedding", Vector(DIM), nullable=False),
    )
    op.create_index("ix_chunks_vpath", "chunks", ["vpath"])
    op.create_index(
        "ix_chunks_embedding_hnsw", "chunks", ["embedding"],
        postgresql_using="hnsw", postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    # keyword leg of hybrid search: generated tsvector column + GIN index
    op.execute(
        "ALTER TABLE chunks ADD COLUMN tsv tsvector "
        "GENERATED ALWAYS AS (to_tsvector('english', body)) STORED"
    )
    op.execute("CREATE INDEX ix_chunks_tsv ON chunks USING gin (tsv)")

    op.create_table(
        "tool_audit",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tool", sa.Text, nullable=False),
        sa.Column("agent", sa.Text, nullable=False),
        sa.Column("tier", sa.Text, nullable=False),
        sa.Column("args_hash", sa.Text, nullable=False),
        sa.Column("args_preview", sa.Text),
        sa.Column("decision", sa.Text, nullable=False),
        sa.Column("outcome", sa.Text, nullable=False),
        sa.Column("duration_ms", sa.Integer),
        sa.Column("trace_id", sa.Text),
        sa.Column("session_id", UUID(as_uuid=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_audit_created", "tool_audit", ["created_at"])
    op.create_index("ix_audit_tool_created", "tool_audit", ["tool", "created_at"])


def downgrade() -> None:
    for t in ("tool_audit", "chunks", "embedding_cache", "ingest_ledger",
              "memory_items", "conversation_turns", "sessions"):
        op.drop_table(t)
