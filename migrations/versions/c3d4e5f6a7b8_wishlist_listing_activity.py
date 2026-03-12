"""wishlist listing activity state

Revision ID: c3d4e5f6a7b8
Revises: 9a6f3e2d1c4b
Create Date: 2026-03-12
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "c3d4e5f6a7b8"
down_revision = "9a6f3e2d1c4b"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("create extension if not exists pgcrypto;")

    op.create_table(
        "wishlist_listing_activity",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("wishlist_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("wishlists.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("car_listing_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("car_listings.id", ondelete="SET NULL"), nullable=True),
        sa.Column("last_valid_run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("source_runs.id", ondelete="SET NULL"), nullable=True),
        sa.Column("listing_identity_key", sa.Text(), nullable=False),
        sa.Column("source_name", sa.Text(), nullable=False),
        sa.Column("source_listing_id", sa.Text(), nullable=True),
        sa.Column("listing_url", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'active'")),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("missing_runs_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("inactive_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("inactive_reason", sa.Text(), nullable=True),
        sa.Column("reactivated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("wishlist_id", "listing_identity_key", name="uq_wishlist_listing_activity_wishlist_identity"),
    )

    op.create_index(
        "ix_wishlist_listing_activity_wishlist_source_status",
        "wishlist_listing_activity",
        ["wishlist_id", "source_name", "status"],
    )
    op.create_index(
        "ix_wishlist_listing_activity_wishlist_last_seen",
        "wishlist_listing_activity",
        ["wishlist_id", "last_seen_at"],
    )

    op.execute(
        """
        create trigger wishlist_listing_activity_updated_at
        before update on wishlist_listing_activity
        for each row
        execute function update_updated_at();
        """
    )


def downgrade():
    op.execute("drop trigger if exists wishlist_listing_activity_updated_at on wishlist_listing_activity;")
    op.drop_index("ix_wishlist_listing_activity_wishlist_last_seen", table_name="wishlist_listing_activity")
    op.drop_index("ix_wishlist_listing_activity_wishlist_source_status", table_name="wishlist_listing_activity")
    op.drop_table("wishlist_listing_activity")
