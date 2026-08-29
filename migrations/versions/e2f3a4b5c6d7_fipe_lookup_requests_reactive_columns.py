"""fipe_lookup_requests_reactive_columns

Revision ID: e2f3a4b5c6d7
Revises: d4e6f8a0b2c4
Create Date: 2026-08-28
"""
from alembic import op
import sqlalchemy as sa


revision = "e2f3a4b5c6d7"
down_revision = "d4e6f8a0b2c4"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("fipe_lookup_requests", sa.Column("listing_make", sa.Text(), nullable=True))
    op.add_column("fipe_lookup_requests", sa.Column("listing_model", sa.Text(), nullable=True))
    op.add_column("fipe_lookup_requests", sa.Column("target_year", sa.Integer(), nullable=True))


def downgrade():
    op.drop_column("fipe_lookup_requests", "target_year")
    op.drop_column("fipe_lookup_requests", "listing_model")
    op.drop_column("fipe_lookup_requests", "listing_make")
