"""merge heads

Revision ID: 02400a324b8d
Revises: 0009_source_metrics, 6bc6fd42271c
Create Date: 2026-01-16 16:52:53.037416

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '02400a324b8d'
down_revision: Union[str, Sequence[str], None] = ('0009_source_metrics', '6bc6fd42271c')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
