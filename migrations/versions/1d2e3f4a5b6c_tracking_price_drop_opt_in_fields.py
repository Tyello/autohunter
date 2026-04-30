"""tracking price drop opt-in fields

Revision ID: 1d2e3f4a5b6c
Revises: 7f2c1b9a11d4
Create Date: 2026-04-30
"""

from alembic import op
import sqlalchemy as sa

revision = '1d2e3f4a5b6c'
down_revision = '7f2c1b9a11d4'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('wishlist_tracked_listings', sa.Column('price_drop_alert_enabled', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column('wishlist_tracked_listings', sa.Column('last_price_drop_alert_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('wishlist_tracked_listings', sa.Column('last_price_drop_alert_price', sa.Numeric(12, 2), nullable=True))
    op.alter_column('wishlist_tracked_listings', 'price_drop_alert_enabled', server_default=None)


def downgrade() -> None:
    op.drop_column('wishlist_tracked_listings', 'last_price_drop_alert_price')
    op.drop_column('wishlist_tracked_listings', 'last_price_drop_alert_at')
    op.drop_column('wishlist_tracked_listings', 'price_drop_alert_enabled')
