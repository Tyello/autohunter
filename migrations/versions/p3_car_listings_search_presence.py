"""car_listings: presenca por busca (last_seen_search_key, missing_runs_count)

Base do reconcile de inatividade (app/services/listing_presence_service.py): guarda a ultima
busca/grupo que trouxe o anuncio e quantas buscas completas seguidas dela nao o trouxeram.
Colunas aditivas e nulas/default 0 (metadata-only no Postgres >= 11); o indice parcial fica
pequeno porque so linhas ja vistas por uma busca entram nele. Nada muda de comportamento
enquanto source_configs.extra.inactive_reconcile.mode estiver 'off' (default).
"""
from alembic import op
import sqlalchemy as sa

revision = "p3_listing_search_presence"
down_revision = "p2_run_id_fk_idx"
branch_labels = None
depends_on = None

INDEX = "ix_car_listings_source_search_key"


def upgrade() -> None:
    op.add_column("car_listings", sa.Column("last_seen_search_key", sa.Text(), nullable=True))
    op.add_column(
        "car_listings",
        sa.Column("missing_runs_count", sa.Integer(), nullable=False, server_default="0"),
    )
    with op.get_context().autocommit_block():
        op.execute(
            f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {INDEX} "
            "ON car_listings (source, last_seen_search_key) WHERE last_seen_search_key IS NOT NULL"
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {INDEX}")
    op.drop_column("car_listings", "missing_runs_count")
    op.drop_column("car_listings", "last_seen_search_key")
