"""merge heads

Revision ID: 0010_merge_heads
Revises: 0007_system_logs, 4814c39d4b73_wishlists_id, 0009_source_metrics, 0004_wishlist_filters, fase1_005_cursors_sold
Create Date: 2026-02-28 00:00:00.000000

"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "0010_merge_heads"
down_revision = ('0007_system_logs', '4814c39d4b73_wishlists_id', '0009_source_metrics', '0004_wishlist_filters', 'fase1_005_cursors_sold')
branch_labels = None
depends_on = None


def upgrade():
    # merge revision — no-op
    pass


def downgrade():
    # merge revision — no-op
    pass
