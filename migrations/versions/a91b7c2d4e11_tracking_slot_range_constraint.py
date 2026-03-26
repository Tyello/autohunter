"""tracking slot range constraint

Revision ID: a91b7c2d4e11
Revises: f1e2d3c4b5a6
Create Date: 2026-03-26
"""

from alembic import op


revision = "a91b7c2d4e11"
down_revision = "f1e2d3c4b5a6"
branch_labels = None
depends_on = None


def upgrade():
    op.create_check_constraint(
        "ck_wishlist_tracked_listing_slot_range",
        "wishlist_tracked_listings",
        "slot >= 1 AND slot <= 3",
    )


def downgrade():
    op.drop_constraint("ck_wishlist_tracked_listing_slot_range", "wishlist_tracked_listings", type_="check")
