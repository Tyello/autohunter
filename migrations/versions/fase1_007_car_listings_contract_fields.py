"""extend car_listings canonical contract fields

Revision ID: fase1_007_car_contract
Revises: bf_agent_001
Create Date: 2026-03-09
"""

from alembic import op
import sqlalchemy as sa


revision = "fase1_007_car_contract"
down_revision = "bf_agent_001"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("car_listings", sa.Column("version", sa.Text(), nullable=True))
    op.add_column("car_listings", sa.Column("seller_type", sa.Text(), nullable=True))
    op.add_column("car_listings", sa.Column("city", sa.Text(), nullable=True))
    op.add_column("car_listings", sa.Column("state", sa.Text(), nullable=True))
    op.add_column("car_listings", sa.Column("color", sa.Text(), nullable=True))

    op.create_index(
        "idx_car_listings_city_state",
        "car_listings",
        ["city", "state"],
        postgresql_where=sa.text("city IS NOT NULL OR state IS NOT NULL"),
    )


def downgrade():
    op.drop_index("idx_car_listings_city_state", table_name="car_listings")
    op.drop_column("car_listings", "color")
    op.drop_column("car_listings", "state")
    op.drop_column("car_listings", "city")
    op.drop_column("car_listings", "seller_type")
    op.drop_column("car_listings", "version")
