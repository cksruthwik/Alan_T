"""initial — sessions + conversation_turns (M0)

Revision ID: 0001_initial
Revises:
Create Date: 2026-06-15
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "sessions",
        sa.Column("id", sa.String(length=26), primary_key=True),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("channel", sa.String(length=16), nullable=False, server_default="api"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_table(
        "conversation_turns",
        sa.Column("id", sa.String(length=26), primary_key=True),
        sa.Column(
            "session_id",
            sa.String(length=26),
            sa.ForeignKey("sessions.id"),
            nullable=False,
        ),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("modality", sa.String(length=16), nullable=False, server_default="text"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_conversation_turns_session_id", "conversation_turns", ["session_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_conversation_turns_session_id", table_name="conversation_turns")
    op.drop_table("conversation_turns")
    op.drop_table("sessions")
