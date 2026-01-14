"""merge heads

Revision ID: 817044be56ec
Revises: 0007_system_logs, 0004_wishlist_filters
Create Date: 2026-01-14 02:24:01.273884

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '817044be56ec'
down_revision: Union[str, Sequence[str], None] = ('0007_system_logs', '0004_wishlist_filters')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
