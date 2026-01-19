"""last_run_at to source_states

Revision ID: 9782264b9233
Revises: 02400a324b8d
Create Date: 2026-01-18 23:00:28.160474

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9782264b9233'
down_revision: Union[str, Sequence[str], None] = '02400a324b8d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "source_states",
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("source_states", "last_run_at")
