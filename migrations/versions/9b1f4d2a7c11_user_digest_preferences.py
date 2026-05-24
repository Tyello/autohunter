"""add user digest preferences

Revision ID: 9b1f4d2a7c11
Revises: fed869eabd8b
Create Date: 2026-05-24
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "9b1f4d2a7c11"
down_revision = "aa21b3c4d5e6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_digest_preferences",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("weekly_digest_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("digest_days", sa.Integer(), nullable=False, server_default=sa.text("7")),
        sa.Column("digest_limit", sa.Integer(), nullable=False, server_default=sa.text("10")),
        sa.Column("last_digest_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_digest_previewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id"),
        sa.CheckConstraint("digest_days >= 1 AND digest_days <= 30", name="ck_user_digest_preferences_days_range"),
        sa.CheckConstraint("digest_limit >= 1 AND digest_limit <= 20", name="ck_user_digest_preferences_limit_range"),
    )
    op.create_index("ix_user_digest_preferences_enabled", "user_digest_preferences", ["weekly_digest_enabled"])


def downgrade() -> None:
    op.drop_index("ix_user_digest_preferences_enabled", table_name="user_digest_preferences")
    op.drop_table("user_digest_preferences")
