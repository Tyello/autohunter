"""add plan and daily_limit_override to users

Revision ID: 8cd5bef4f6b6
Revises: 70e3d36bfd23
Create Date: 2026-01-15 23:35:56.083386

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8cd5bef4f6b6'
down_revision: Union[str, Sequence[str], None] = '70e3d36bfd23'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("plan", sa.Text(), nullable=False, server_default="free"))
    op.add_column("users", sa.Column("daily_limit_override", sa.Integer(), nullable=True))

    op.create_index("ix_users_plan", "users", ["plan"], unique=False)
    op.create_index("ix_users_daily_limit_override", "users", ["daily_limit_override"], unique=False)

def downgrade() -> None:
    op.drop_index("ix_users_daily_limit_override", table_name="users")
    op.drop_index("ix_users_plan", table_name="users")
    op.drop_column("users", "daily_limit_override")
    op.drop_column("users", "plan")
