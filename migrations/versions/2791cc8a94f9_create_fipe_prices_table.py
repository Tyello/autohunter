"""create fipe_prices table

Revision ID: 2791cc8a94f9
Revises: 2c0759ec3788
Create Date: 2026-01-13 21:38:01.400786

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2791cc8a94f9'
down_revision: Union[str, Sequence[str], None] = '2c0759ec3788'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    op.create_table(
        "fipe_prices",
        sa.Column("id", sa.dialects.postgresql.UUID(), primary_key=True),

        sa.Column("brand", sa.Text(), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("version", sa.Text()),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("fuel", sa.Text()),

        sa.Column("price", sa.Numeric(), nullable=False),
        sa.Column("reference_month", sa.Date(), nullable=False),

        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),

        sa.UniqueConstraint(
            "brand", "model", "version", "year", "fuel", "reference_month",
            name="uq_fipe_reference"
        )
    )

    op.execute("""
    create trigger fipe_prices_updated_at
    before update on fipe_prices
    for each row
    execute function update_updated_at();
    """)


def downgrade():
    op.drop_table("fipe_prices")
