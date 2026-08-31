"""car_listings title/location trigram index for ILIKE search

Revision ID: d3e5f7a9b1c2
Revises: 4b89ead23dfb
Create Date: 2026-08-30

Contexto: pg_stat_statements mostrou buscas manuais `title ILIKE '%termo%'` /
`(title ILIKE %s OR location ILIKE %s)` (app/services/search_service.py,
app/services/facet_search_service.py) sem cobertura de índice — um btree normal
não serve para ILIKE com wildcard nas duas pontas. Índice GIN trigram cobre
ILIKE/LIKE com wildcard em qualquer posição.
"""
from typing import Sequence, Union

from alembic import op


revision: str = "d3e5f7a9b1c2"
down_revision: Union[str, Sequence[str], None] = "4b89ead23dfb"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    is_pg = bind.dialect.name == "postgresql"

    if is_pg:
        op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
        with op.get_context().autocommit_block():
            op.execute(
                "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
                "idx_car_listings_title_trgm ON car_listings USING gin (title gin_trgm_ops)"
            )
            op.execute(
                "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
                "idx_car_listings_location_trgm ON car_listings USING gin (location gin_trgm_ops)"
            )
    # sqlite (tests) has no trigram support and no ILIKE cost concern — skip.


def downgrade() -> None:
    bind = op.get_bind()
    is_pg = bind.dialect.name == "postgresql"

    if is_pg:
        with op.get_context().autocommit_block():
            op.execute("DROP INDEX CONCURRENTLY IF EXISTS idx_car_listings_location_trgm")
            op.execute("DROP INDEX CONCURRENTLY IF EXISTS idx_car_listings_title_trgm")
