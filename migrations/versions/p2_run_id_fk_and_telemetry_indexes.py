"""indices em run_id (FKs p/ source_runs) e telemetry_events.created_at

Retencao de source_runs (DELETE ... LIMIT) dispara ON DELETE SET NULL em system_logs,
telemetry_events e wishlist_listing_activity; sem indice nas FKs cada lote varria as
tabelas inteiras (~6,5s por lote em prod). telemetry_events tambem nao tinha indice em
created_at (DELETE de retencao por seq scan, ~1,9s por lote).

Indices parciais (run_id IS NOT NULL) ficam pequenos. CONCURRENTLY nao roda em transacao.
"""
from alembic import op

revision = "p2_run_id_fk_idx"
down_revision = "9b2d4f6a8c1e"
branch_labels = None
depends_on = None

INDEXES = (
    ("ix_system_logs_run_id", "system_logs", "run_id", "run_id IS NOT NULL"),
    ("ix_telemetry_events_run_id", "telemetry_events", "run_id", "run_id IS NOT NULL"),
    ("ix_wla_last_valid_run_id", "wishlist_listing_activity", "last_valid_run_id", "last_valid_run_id IS NOT NULL"),
    ("ix_telemetry_events_created_at", "telemetry_events", "created_at", None),
)


def upgrade() -> None:
    with op.get_context().autocommit_block():
        for name, table, col, where in INDEXES:
            suffix = f" WHERE {where}" if where else ""
            op.execute(f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {name} ON {table} ({col}){suffix}")


def downgrade() -> None:
    with op.get_context().autocommit_block():
        for name, *_ in INDEXES:
            op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {name}")
