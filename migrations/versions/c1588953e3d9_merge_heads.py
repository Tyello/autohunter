"""merge heads

Revision ID: c1588953e3d9
Revises: 4814c39d4b73_wishlists_id, 817044be56ec
Create Date: 2026-01-14 02:27:03.967717

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c1588953e3d9'
down_revision: Union[str, Sequence[str], None] = ('4814c39d4b73_wishlists_id', '817044be56ec')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
