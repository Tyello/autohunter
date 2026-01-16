"""add last_daily_limit_notice_at to users

Revision ID: 70e3d36bfd23
Revises: 31a3a2c240bd
Create Date: 2026-01-15 23:16:48.119038

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '70e3d36bfd23'
down_revision: Union[str, Sequence[str], None] = '31a3a2c240bd'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("last_daily_limit_notice_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_users_last_daily_limit_notice_at",
        "users",
        ["last_daily_limit_notice_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_users_last_daily_limit_notice_at", table_name="users")
    op.drop_column("users", "last_daily_limit_notice_at")