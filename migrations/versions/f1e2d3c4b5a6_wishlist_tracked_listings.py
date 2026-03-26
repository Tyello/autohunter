"""wishlist tracked listings

Revision ID: f1e2d3c4b5a6
Revises: c3d4e5f6a7b8
Create Date: 2026-03-26
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "f1e2d3c4b5a6"
down_revision = "c3d4e5f6a7b8"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("create extension if not exists pgcrypto;")

    op.create_table(
        "wishlist_tracked_listings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("wishlist_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("wishlists.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("car_listing_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("car_listings.id", ondelete="SET NULL"), nullable=True),
        sa.Column("slot", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("wishlist_id", "car_listing_id", name="uq_wishlist_tracked_listing_pair"),
        sa.UniqueConstraint("wishlist_id", "slot", name="uq_wishlist_tracked_listing_slot"),
    )

    op.create_index(
        "ix_wishlist_tracked_listings_wishlist_slot",
        "wishlist_tracked_listings",
        ["wishlist_id", "slot"],
    )

    op.execute(
        """
        create trigger wishlist_tracked_listings_updated_at
        before update on wishlist_tracked_listings
        for each row
        execute function update_updated_at();
        """
    )


def downgrade():
    op.execute("drop trigger if exists wishlist_tracked_listings_updated_at on wishlist_tracked_listings;")
    op.drop_index("ix_wishlist_tracked_listings_wishlist_slot", table_name="wishlist_tracked_listings")
    op.drop_table("wishlist_tracked_listings")
