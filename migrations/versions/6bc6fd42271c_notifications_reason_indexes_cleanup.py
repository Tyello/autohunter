"""notifications reason indexes cleanup

Revision ID: 6bc6fd42271c
Revises: 00667b84d001
Create Date: 2026-01-16 09:40:39.848987

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '6bc6fd42271c'
down_revision: Union[str, Sequence[str], None] = '00667b84d001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("notifications", sa.Column("reason", sa.Text(), nullable=True))

    op.create_index(
        "ix_notifications_status_created_at",
        "notifications",
        ["status", "created_at"],
        unique=False,
    )

    op.create_index(
        "ix_notifications_user_status_created_at",
        "notifications",
        ["user_id", "status", "created_at"],
        unique=False,
    )

    op.create_index(
        "ix_notifications_reason",
        "notifications",
        ["reason"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_notifications_reason", table_name="notifications")
    op.drop_index("ix_notifications_user_status_created_at", table_name="notifications")
    op.drop_index("ix_notifications_status_created_at", table_name="notifications")
    op.drop_column("notifications", "reason")