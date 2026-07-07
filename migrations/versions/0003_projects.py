"""projects + session grouping/activity — the fullscale-chatbot pass

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-05

"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "projects",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.Text, nullable=False, unique=True),
        sa.Column("instructions", sa.Text, nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.add_column("sessions", sa.Column("project_id", UUID(as_uuid=True),
                                        sa.ForeignKey("projects.id"), nullable=True))
    op.add_column("sessions", sa.Column("last_message_at", sa.DateTime(timezone=True), nullable=True))
    # backfill activity so existing chats sort sanely
    op.execute("""
        UPDATE sessions s SET last_message_at = (
            SELECT max(t.created_at) FROM conversation_turns t WHERE t.session_id = s.id)
    """)


def downgrade() -> None:
    op.drop_column("sessions", "last_message_at")
    op.drop_column("sessions", "project_id")
    op.drop_table("projects")
