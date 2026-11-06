"""car_listings: indice parcial (source, last_seen_at) WHERE status='ativo'; remove 2 indices sem uso

Contexto (producao, Supabase Free/Nano, 2026-11-06): a contagem/UPDATE de "anuncios nao vistos ha
N dias" (`listing_presence_service.mark_stale_listings_inactive`) filtra por
`source = ? AND status = 'ativo' AND last_seen_at < ?`. Sem indice composto o planner combinava
`car_listings_source_idx` + heap (5.9k paginas, ~5s a frio). O indice parcial permite Index Only Scan
(~1.8 MB estimado via hypopg).

Remocoes (0 scans medidos desde 2026-10-19; cada indice custa escrita no upsert de ~25 linhas):
- `car_listings_updated_at_idx`: a unica ordenacao por updated_at filtra antes por
  `cross_source_fingerprint` (<= 8 linhas, cross_source_dedupe_service).
- `idx_car_listings_status_active`: redundante com `car_listings_status_idx`.
`idx_car_listings_location_trgm` e MANTIDO: `search_service` usa `location ILIKE` na busca manual.

Nao toca tabelas protegidas (docs/DB_GUARDRAILS.md). Postgres: CONCURRENTLY fora de transacao.
Reversivel: downgrade recria os dois indices e remove o novo.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "p4_listing_last_seen_idx"
down_revision: Union[str, Sequence[str], None] = "p3_listing_search_presence"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

NEW_INDEX = "ix_car_listings_source_last_seen_active"
DROP_UPDATED_AT = "car_listings_updated_at_idx"
DROP_STATUS_ACTIVE = "idx_car_listings_status_active"


def upgrade() -> None:
    is_pg = op.get_bind().dialect.name == "postgresql"

    if is_pg:
        with op.get_context().autocommit_block():
            op.execute(
                f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {NEW_INDEX} "
                "ON car_listings (source, last_seen_at) WHERE status = 'ativo'"
            )
            op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {DROP_UPDATED_AT}")
            op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {DROP_STATUS_ACTIVE}")
    else:
        op.create_index(
            NEW_INDEX,
            "car_listings",
            ["source", "last_seen_at"],
            sqlite_where=sa.text("status = 'ativo'"),
        )
        op.execute(f"DROP INDEX IF EXISTS {DROP_UPDATED_AT}")
        op.execute(f"DROP INDEX IF EXISTS {DROP_STATUS_ACTIVE}")


def downgrade() -> None:
    is_pg = op.get_bind().dialect.name == "postgresql"

    if is_pg:
        with op.get_context().autocommit_block():
            op.execute(
                f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {DROP_STATUS_ACTIVE} "
                "ON car_listings (status) WHERE status = 'ativo'"
            )
            op.execute(
                f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {DROP_UPDATED_AT} "
                "ON car_listings (updated_at)"
            )
            op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {NEW_INDEX}")
    else:
        op.create_index(
            DROP_STATUS_ACTIVE,
            "car_listings",
            ["status"],
            sqlite_where=sa.text("status = 'ativo'"),
        )
        op.create_index(DROP_UPDATED_AT, "car_listings", ["updated_at"])
        op.execute(f"DROP INDEX IF EXISTS {NEW_INDEX}")
