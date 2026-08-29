"""hot query index coverage audit (car_listings dedupe, notifications dedupe/status, wishlist matching)

Revision ID: f4a8c1d3e7b2
Revises: e2f3a4b5c6d7, p0_02_fipe_update_runs, p1_notif_dq_partial
Create Date: 2026-08-29

Contexto (spec: specs/010-fipe-reactive-bootstrap audit de indices):

Introspecao direta em producao (pg_indexes / pg_constraint) mostrou que o
schema real diverge dos migrations ja mergeados na arvore por causa de
multiplos heads do alembic historicamente aplicados fora de ordem
(alembic_version tinha 3 heads simultaneos: d4e6f8a0b2c4, p0_02_fipe_update_runs,
p1_notif_dq_partial). Como resultado, dois constraints que o codigo ja
pressupoe NUNCA existiram em producao:

1. `car_listings` nao tem unique(source, external_id). O bulk upsert em
   app/repositories/car_listings_repo.py usa
   `on_conflict_do_update(index_elements=["source", "external_id"])`, que
   exige um indice unico exatamente nessas colunas para funcionar. Sem ele,
   TODA chamada cai no fallback `_fallback_upsert_without_constraint`
   (SELECT+INSERT/UPDATE por linha, sem bulk). Ja gerou duplicatas reais em
   producao (10 linhas / 5 pares, todas fonte "olx", sem FK de notifications
   ou wishlist_listing_activity apontando pra elas).

2. `notifications` nao tem unique(wishlist_id, car_listing_id), apesar da
   migration 31a3a2c240bd (ancestral no grafo) declarar essa constraint.
   Verificado: nao ha grupos duplicados com wishlist_id NAO nulo (seguro
   criar o indice unico agora).

3. `ix_notifications_status_created_at`, `ix_notifications_user_status_created_at`
   e `ix_notifications_reason` (migration 6bc6fd42271c, tambem ancestral)
   igualmente ausentes em producao. Recriados aqui.

4. `wishlist_listing_activity` so tem indice em (wishlist_id) isolado; a
   query de matching de listings ativas (wishlist_id + status='active' +
   car_listing_id IS NOT NULL) faz Filter sequencial sobre o resultado do
   indice em vez de Index Cond. Adicionado composto (wishlist_id, status).

NAO alterado (ja adequado, confirmado via pg_indexes + EXPLAIN ANALYZE):
- `ix_notifications_delivery_queue_active` (partial WHERE status IN
  ('queued','processing')) ja cobre a fila de pendentes do sender.
- `auction_lots` e `fipe_catalog_entries` ja tem cobertura composta
  adequada para os filtros hot (source+status, make/model/year,
  reference_month+vehicle_type).

Todos os CREATE INDEX rodam CONCURRENTLY fora de transacao (autocommit
block) para nao bloquear producao. A limpeza de duplicatas de car_listings
e' feita antes do indice unico e e' IRREVERSIVEL (nao restaurada no
downgrade) -- so remove linhas duplicadas sem nenhuma FK filha.
"""
from alembic import op
import sqlalchemy as sa


revision = "f4a8c1d3e7b2"
down_revision = ("e2f3a4b5c6d7", "p0_02_fipe_update_runs", "p1_notif_dq_partial")
branch_labels = None
depends_on = None


_DEDUPE_CAR_LISTINGS_SQL = """
WITH ranked AS (
    SELECT
        id,
        ROW_NUMBER() OVER (
            PARTITION BY source, external_id
            ORDER BY created_at ASC, id ASC
        ) AS rn
    FROM car_listings
),
losers AS (
    SELECT id FROM ranked WHERE rn > 1
)
DELETE FROM car_listings cl
USING losers
WHERE cl.id = losers.id
  AND NOT EXISTS (SELECT 1 FROM notifications n WHERE n.car_listing_id = cl.id)
  AND NOT EXISTS (SELECT 1 FROM wishlist_listing_activity w WHERE w.car_listing_id = cl.id)
"""


def upgrade() -> None:
    bind = op.get_bind()
    is_pg = bind.dialect.name == "postgresql"

    # 1) Dedupe car_listings so the unique index below can be created.
    #    Duplicate groups whose extra rows already have children (notifications /
    #    wishlist_listing_activity) are intentionally left alone; if any remain,
    #    the unique index creation will fail loudly instead of silently dropping data.
    op.execute(_DEDUPE_CAR_LISTINGS_SQL)

    if is_pg:
        with op.get_context().autocommit_block():
            op.execute(
                "CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS "
                "uq_car_listings_source_external_id ON car_listings (source, external_id)"
            )
            op.execute(
                "CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS "
                "uq_notifications_wishlist_listing ON notifications (wishlist_id, car_listing_id)"
            )
            op.execute(
                "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
                "ix_notifications_status_created_at ON notifications (status, created_at)"
            )
            op.execute(
                "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
                "ix_notifications_user_status_created_at ON notifications (user_id, status, created_at)"
            )
            op.execute(
                "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
                "ix_notifications_reason ON notifications (reason)"
            )
            op.execute(
                "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
                "ix_wishlist_activity_wishlist_status ON wishlist_listing_activity (wishlist_id, status)"
            )
    else:
        op.create_index(
            "uq_car_listings_source_external_id", "car_listings", ["source", "external_id"], unique=True
        )
        op.create_index(
            "uq_notifications_wishlist_listing", "notifications", ["wishlist_id", "car_listing_id"], unique=True
        )
        op.create_index("ix_notifications_status_created_at", "notifications", ["status", "created_at"])
        op.create_index(
            "ix_notifications_user_status_created_at", "notifications", ["user_id", "status", "created_at"]
        )
        op.create_index("ix_notifications_reason", "notifications", ["reason"])
        op.create_index(
            "ix_wishlist_activity_wishlist_status", "wishlist_listing_activity", ["wishlist_id", "status"]
        )


def downgrade() -> None:
    bind = op.get_bind()
    is_pg = bind.dialect.name == "postgresql"

    if is_pg:
        with op.get_context().autocommit_block():
            op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_wishlist_activity_wishlist_status")
            op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_notifications_reason")
            op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_notifications_user_status_created_at")
            op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_notifications_status_created_at")
            op.execute("DROP INDEX CONCURRENTLY IF EXISTS uq_notifications_wishlist_listing")
            op.execute("DROP INDEX CONCURRENTLY IF EXISTS uq_car_listings_source_external_id")
    else:
        op.drop_index("ix_wishlist_activity_wishlist_status", table_name="wishlist_listing_activity")
        op.drop_index("ix_notifications_reason", table_name="notifications")
        op.drop_index("ix_notifications_user_status_created_at", table_name="notifications")
        op.drop_index("ix_notifications_status_created_at", table_name="notifications")
        op.drop_index("uq_notifications_wishlist_listing", table_name="notifications")
        op.drop_index("uq_car_listings_source_external_id", table_name="car_listings")

    # NOTE: duplicate car_listings rows removed in upgrade() are not restored.
