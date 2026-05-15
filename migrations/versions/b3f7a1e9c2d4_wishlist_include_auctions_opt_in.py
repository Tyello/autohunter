"""add include_auctions opt-in to wishlists

Revision ID: b3f7a1e9c2d4
Revises: aa9d2f11c123
Create Date: 2026-05-15
"""

from alembic import op
import sqlalchemy as sa


revision = "b3f7a1e9c2d4"
down_revision = "aa9d2f11c123"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "wishlists",
        sa.Column("include_auctions", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("wishlists", "include_auctions")
