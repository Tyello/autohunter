"""add unique constraint notifications wishlist listing

Revision ID: 31a3a2c240bd
Revises: ec4a5f769526
Create Date: 2026-01-14 14:10:39.922633

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '31a3a2c240bd'
down_revision: Union[str, Sequence[str], None] = 'ec4a5f769526'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    op.create_unique_constraint(
        "uq_notifications_wishlist_listing",
        "notifications",
        ["wishlist_id", "car_listing_id"],
    )

def downgrade():
    op.drop_constraint(
        "uq_notifications_wishlist_listing",
        "notifications",
        type_="unique"
    )
