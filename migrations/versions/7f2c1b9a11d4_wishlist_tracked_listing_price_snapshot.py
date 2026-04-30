"""wishlist tracked listing price snapshot

Revision ID: 7f2c1b9a11d4
Revises: 0be3b0c71883
Create Date: 2026-04-30 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7f2c1b9a11d4'
down_revision: Union[str, Sequence[str], None] = '0be3b0c71883'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('wishlist_tracked_listings', sa.Column('initial_price', sa.Numeric(precision=12, scale=2), nullable=True))
    op.add_column('wishlist_tracked_listings', sa.Column('last_observed_price', sa.Numeric(precision=12, scale=2), nullable=True))
    op.add_column('wishlist_tracked_listings', sa.Column('last_price_change_amount', sa.Numeric(precision=12, scale=2), nullable=True))
    op.add_column('wishlist_tracked_listings', sa.Column('last_price_change_pct', sa.Numeric(precision=7, scale=4), nullable=True))
    op.add_column('wishlist_tracked_listings', sa.Column('last_price_change_direction', sa.Text(), nullable=True))
    op.add_column('wishlist_tracked_listings', sa.Column('last_price_change_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('wishlist_tracked_listings', sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('wishlist_tracked_listings', sa.Column('listing_status', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('wishlist_tracked_listings', 'listing_status')
    op.drop_column('wishlist_tracked_listings', 'last_seen_at')
    op.drop_column('wishlist_tracked_listings', 'last_price_change_at')
    op.drop_column('wishlist_tracked_listings', 'last_price_change_direction')
    op.drop_column('wishlist_tracked_listings', 'last_price_change_pct')
    op.drop_column('wishlist_tracked_listings', 'last_price_change_amount')
    op.drop_column('wishlist_tracked_listings', 'last_observed_price')
    op.drop_column('wishlist_tracked_listings', 'initial_price')
