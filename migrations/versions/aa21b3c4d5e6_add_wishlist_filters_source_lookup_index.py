"""add wishlist_filters source lookup index

Revision ID: aa21b3c4d5e6
Revises: f6a1b2c3d4e5
Create Date: 2026-05-21 00:00:00.000000
"""
from alembic import op


# revision identifiers, used by Alembic.
revision = "aa21b3c4d5e6"
down_revision = "f6a1b2c3d4e5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_wishlist_filters_source_lookup",
        "wishlist_filters",
        ["wishlist_id", "field", "operator", "value"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_wishlist_filters_source_lookup", table_name="wishlist_filters")
