"""create car_listings table

Revision ID: fb21eb347192
Revises: b4a2e22ec9cc
Create Date: 2026-01-13 21:33:51.334829

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'fb21eb347192'
down_revision: Union[str, Sequence[str], None] = 'b4a2e22ec9cc'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    op.create_table(
        "car_listings",
        sa.Column("id", sa.dialects.postgresql.UUID(), primary_key=True),

        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("external_id", sa.Text(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),

        sa.Column("title", sa.Text()),
        sa.Column("description", sa.Text()),

        sa.Column("brand", sa.Text()),
        sa.Column("model", sa.Text()),
        sa.Column("version", sa.Text()),
        sa.Column("year", sa.Integer()),
        sa.Column("color", sa.Text()),
        sa.Column("fuel", sa.Text()),
        sa.Column("transmission", sa.Text()),
        sa.Column("mileage", sa.Integer()),

        sa.Column("price", sa.Numeric(), nullable=False),
        sa.Column("fipe_price", sa.Numeric()),

        sa.Column("location_state", sa.Text()),
        sa.Column("location_city", sa.Text()),

        sa.Column("thumbnail_url", sa.Text()),

        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("last_seen_at", sa.DateTime(timezone=True)),
        sa.Column("is_active", sa.Boolean(), server_default="true"),

        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),

        sa.UniqueConstraint("source", "external_id", name="uq_car_listing")
    )

    op.execute("""
    create trigger car_listings_updated_at
    before update on car_listings
    for each row
    execute function update_updated_at();
    """)


def downgrade() -> None:
    """Downgrade schema."""
    pass
