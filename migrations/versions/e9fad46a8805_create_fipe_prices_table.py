"""create fipe_prices table

Revision ID: e9fad46a8805
Revises: fb21eb347192
Create Date: 2026-01-13 21:34:11.118779

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e9fad46a8805'
down_revision: Union[str, Sequence[str], None] = 'fb21eb347192'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
