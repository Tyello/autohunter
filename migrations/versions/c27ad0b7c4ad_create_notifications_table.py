"""create notifications table

Revision ID: c27ad0b7c4ad
Revises: e9fad46a8805
Create Date: 2026-01-13 21:34:15.927388

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c27ad0b7c4ad'
down_revision: Union[str, Sequence[str], None] = 'e9fad46a8805'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
