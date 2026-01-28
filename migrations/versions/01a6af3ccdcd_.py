"""empty message

Revision ID: 01a6af3ccdcd
Revises: 9782264b9233, d1a7c0f6b2aa
Create Date: 2026-01-27 22:07:40.222883

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '01a6af3ccdcd'
down_revision: Union[str, Sequence[str], None] = ('9782264b9233', 'd1a7c0f6b2aa')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
