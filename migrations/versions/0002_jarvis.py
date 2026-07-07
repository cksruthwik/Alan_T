"""contacts + documents + task_runs — the Jarvis build (Docs_COMPLEX 100% pass)

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-05

"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "contacts",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("email", sa.Text),
        sa.Column("phone", sa.Text),
        sa.Column("notes", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_contacts_name", "contacts", ["name"])

    op.create_table(
        "documents",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("content", sa.Text, nullable=False, server_default=""),
        sa.Column("format", sa.Text, nullable=False, server_default="markdown"),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_documents_updated", "documents", ["updated_at"])

    op.create_table(
        "task_runs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("goal", sa.Text, nullable=False),
        sa.Column("plan", JSONB, nullable=False),
        sa.Column("step_results", JSONB),
        sa.Column("status", sa.Text, nullable=False, server_default="planned"),
        sa.Column("reflection", JSONB),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_task_runs_created", "task_runs", ["created_at"])


def downgrade() -> None:
    op.drop_table("task_runs")
    op.drop_table("documents")
    op.drop_table("contacts")
