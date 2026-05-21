"""add notifications sent-at index for daily limit counts

Revision ID: f6a1b2c3d4e5
Revises: e1f2a3b4c5d6
Create Date: 2026-05-21
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f6a1b2c3d4e5"
down_revision: Union[str, Sequence[str], None] = "e1f2a3b4c5d6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


INDEX_NAME = "ix_notifications_user_sent_today"


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.create_index(
            INDEX_NAME,
            "notifications",
            ["user_id", "sent_at"],
            unique=False,
            postgresql_where=sa.text("status = 'sent'"),
        )
    else:
        op.create_index(
            INDEX_NAME,
            "notifications",
            ["user_id", "status", "sent_at"],
            unique=False,
        )


def downgrade() -> None:
    op.drop_index(INDEX_NAME, table_name="notifications")
