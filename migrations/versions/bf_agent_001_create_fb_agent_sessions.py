"""create fb_agent_sessions

Revision ID: bf_agent_001
Revises: 3b9f8d1c4a2f
Create Date: 2026-03-02 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "bf_agent_001"
down_revision = "3b9f8d1c4a2f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "fb_agent_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column("pairing_code", sa.String(length=16), nullable=True),
        sa.Column("pairing_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("pairing_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("agent_id", sa.String(length=64), nullable=True),
        sa.Column("agent_version", sa.String(length=32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_check_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_ok_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_kind", sa.String(length=32), nullable=True),
        sa.Column("last_error_message", sa.String(length=256), nullable=True),
        sa.Column("action_hint", sa.String(length=128), nullable=True),
        sa.Column("bootstrap_token", sa.String(length=128), nullable=True),
        sa.Column("bootstrap_token_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("bootstrap_token_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id"),
    )
    op.create_index(op.f("ix_fb_agent_sessions_user_id"), "fb_agent_sessions", ["user_id"], unique=True)
    op.create_index(op.f("ix_fb_agent_sessions_pairing_code"), "fb_agent_sessions", ["pairing_code"], unique=False)
    op.create_index(op.f("ix_fb_agent_sessions_status"), "fb_agent_sessions", ["status"], unique=False)
    op.create_index(op.f("ix_fb_agent_sessions_bootstrap_token"), "fb_agent_sessions", ["bootstrap_token"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_fb_agent_sessions_bootstrap_token"), table_name="fb_agent_sessions")
    op.drop_index(op.f("ix_fb_agent_sessions_status"), table_name="fb_agent_sessions")
    op.drop_index(op.f("ix_fb_agent_sessions_pairing_code"), table_name="fb_agent_sessions")
    op.drop_index(op.f("ix_fb_agent_sessions_user_id"), table_name="fb_agent_sessions")
    op.drop_table("fb_agent_sessions")
