"""merge fase1_008 with main head

Revision ID: 0be3b0c71883
Revises: fase1_008_car_listing_new_fields, fed869eabd8b
Create Date: 2026-04-29 21:36:35.902754

"""
from typing import Sequence, Union

# revision identifiers, used by Alembic.
revision: str = '0be3b0c71883'
down_revision: Union[str, Sequence[str], None] = ('fase1_008_car_listing_new_fields', 'fed869eabd8b')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
