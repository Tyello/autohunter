"""merge current heads

Revision ID: fed869eabd8b
Revises: 2b7c9f4d1eaa, a91b7c2d4e11
Create Date: 2026-04-29 18:32:52.546807

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'fed869eabd8b'
down_revision: Union[str, Sequence[str], None] = ('2b7c9f4d1eaa', 'a91b7c2d4e11')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
