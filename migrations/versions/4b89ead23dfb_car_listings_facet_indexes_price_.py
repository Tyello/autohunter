"""car_listings facet indexes price mileage status

Revision ID: 4b89ead23dfb
Revises: 211de43e94c3
Create Date: 2026-08-30 08:57:19.160209

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4b89ead23dfb'
down_revision: Union[str, Sequence[str], None] = '211de43e94c3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    is_pg = bind.dialect.name == "postgresql"

    if is_pg:
        with op.get_context().autocommit_block():
            op.execute(
                "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
                "idx_car_listings_price ON car_listings (price) "
                "WHERE price IS NOT NULL"
            )
            op.execute(
                "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
                "idx_car_listings_mileage_km ON car_listings (mileage_km) "
                "WHERE mileage_km IS NOT NULL"
            )
            op.execute(
                "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
                "idx_car_listings_status_active ON car_listings (status) "
                "WHERE status = 'ativo'"
            )
    else:
        op.create_index("idx_car_listings_price", "car_listings", ["price"])
        op.create_index("idx_car_listings_mileage_km", "car_listings", ["mileage_km"])
        op.create_index("idx_car_listings_status_active", "car_listings", ["status"])


def downgrade() -> None:
    bind = op.get_bind()
    is_pg = bind.dialect.name == "postgresql"

    if is_pg:
        with op.get_context().autocommit_block():
            op.execute("DROP INDEX CONCURRENTLY IF EXISTS idx_car_listings_status_active")
            op.execute("DROP INDEX CONCURRENTLY IF EXISTS idx_car_listings_mileage_km")
            op.execute("DROP INDEX CONCURRENTLY IF EXISTS idx_car_listings_price")
    else:
        op.drop_index("idx_car_listings_status_active", table_name="car_listings")
        op.drop_index("idx_car_listings_mileage_km", table_name="car_listings")
        op.drop_index("idx_car_listings_price", table_name="car_listings")
