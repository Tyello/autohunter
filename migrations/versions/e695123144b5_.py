"""empty message

Revision ID: e695123144b5
Revises: 96ab02de94f0, b7c1c9a0d8e0
Create Date: 2026-02-02 20:55:08.681539

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e695123144b5'
down_revision: Union[str, Sequence[str], None] = ('96ab02de94f0', 'b7c1c9a0d8e0')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
