"""create system_logs table

Revision ID: 2c0759ec3788
Revises: c27ad0b7c4ad
Create Date: 2026-01-13 21:34:20.462904

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2c0759ec3788'
down_revision: Union[str, Sequence[str], None] = 'c27ad0b7c4ad'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
