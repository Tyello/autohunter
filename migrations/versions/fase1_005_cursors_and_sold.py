"""incremental cursors + sold flag

Revision ID: fase1_005_cursors_sold
Revises: fase1_004_seed_turboclass_source
Create Date: 2026-02-22

Adds:
- source_url_cursors: per-(source,url) last_seen cursor for incremental scraping
- car_listings.is_sold + car_listings.sold_at: to avoid notifying sold items
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "fase1_005_cursors_sold"
down_revision = "fase1_004_seed_turboclass"
branch_labels = None
depends_on = None


def upgrade():
    # gen_random_uuid() comes from pgcrypto
    op.execute("create extension if not exists pgcrypto;")

    # 1) Per-(source,url) incremental cursor
    op.create_table(
        "source_url_cursors",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("last_external_id", sa.Text(), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("runs", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("source", "url", name="uq_source_url_cursors_source_url"),
    )
    op.create_index("ix_source_url_cursors_source_created_at", "source_url_cursors", ["source", "created_at"])
    op.create_index("ix_source_url_cursors_source_url", "source_url_cursors", ["source", "url"])

    op.execute(
        """
        create trigger source_url_cursors_updated_at
        before update on source_url_cursors
        for each row
        execute function update_updated_at();
        """
    )

    # 2) Sold flag on listings
    op.add_column(
        "car_listings",
        sa.Column("is_sold", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column(
        "car_listings",
        sa.Column("sold_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_car_listings_is_sold",
        "car_listings",
        ["is_sold"],
    )


def downgrade():
    op.drop_index("ix_car_listings_is_sold", table_name="car_listings")
    op.drop_column("car_listings", "sold_at")
    op.drop_column("car_listings", "is_sold")

    op.execute("drop trigger if exists source_url_cursors_updated_at on source_url_cursors;")
    op.drop_index("ix_source_url_cursors_source_url", table_name="source_url_cursors")
    op.drop_index("ix_source_url_cursors_source_created_at", table_name="source_url_cursors")
    op.drop_table("source_url_cursors")
