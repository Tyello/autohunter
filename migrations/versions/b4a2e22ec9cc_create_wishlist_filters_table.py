"""create wishlist_filters table

Revision ID: b4a2e22ec9cc
Revises: 230e2860c629
Create Date: 2026-01-13 21:33:37.536007

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b4a2e22ec9cc'
down_revision: Union[str, Sequence[str], None] = '230e2860c629'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    op.create_table(
        "wishlist_filters",
        sa.Column("id", sa.dialects.postgresql.UUID(), primary_key=True),
        sa.Column("wishlist_id", sa.dialects.postgresql.UUID(), sa.ForeignKey("wishlists.id", ondelete="CASCADE")),

        sa.Column("brand", sa.Text(), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("version", sa.Text()),

        sa.Column("min_year", sa.Integer()),
        sa.Column("max_year", sa.Integer()),
        sa.Column("min_price", sa.Numeric()),
        sa.Column("max_price", sa.Numeric()),

        sa.Column("color", sa.Text()),
        sa.Column("fuel", sa.Text()),
        sa.Column("transmission", sa.Text()),
        sa.Column("mileage_max", sa.Integer()),

        sa.Column("state", sa.Text()),
        sa.Column("city", sa.Text()),

        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now())
    )

    op.execute("""
    create trigger wishlist_filters_updated_at
    before update on wishlist_filters
    for each row
    execute function update_updated_at();
    """)


def downgrade() -> None:
    """Downgrade schema."""
    pass
