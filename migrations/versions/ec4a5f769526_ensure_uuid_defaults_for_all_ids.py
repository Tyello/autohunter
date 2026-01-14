"""ensure uuid defaults for all ids

Revision ID: ec4a5f769526
Revises: b2c22cf5e571
Create Date: 2026-01-14 02:42:56.849429

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ec4a5f769526'
down_revision: Union[str, Sequence[str], None] = 'b2c22cf5e571'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TABLES = [
    "users",
    "wishlists",
    "wishlist_filters",
    "car_listings",
    "fipe_prices",
    "notifications",
    "system_logs",
]


def upgrade():
    # gen_random_uuid() vem do pgcrypto
    op.execute("create extension if not exists pgcrypto;")

    for t in TABLES:
        op.execute(f"alter table {t} alter column id set default gen_random_uuid();")


def downgrade():
    for t in TABLES:
        op.execute(f"alter table {t} alter column id drop default;")