"""notifications: make delivery-queue index partial (hot claim path)

Substitui ix_notifications_delivery_queue por uma versão PARCIAL
(WHERE status IN ('queued','processing')), de modo que o índice contenha
apenas o backlog vivo em vez do histórico inteiro de notificações.

Ganho: o índice da query de claim do sender (rodada a cada tick, com
FOR UPDATE SKIP LOCKED) passa a caber em cache e o autovacuum fica barato.
Crítico em hardware com I/O lento (Raspberry Pi).

NOTA: CREATE/DROP INDEX CONCURRENTLY não roda dentro de transação.
down_revision deve apontar para o head atual da sua linha de migração
(provavelmente 'e8d0d6f4a21b'); ajuste antes de aplicar.
"""
from alembic import op

revision = "p1_notif_dq_partial"
down_revision = "5c8f1a2b3d4e"
branch_labels = None
depends_on = None

OLD = "ix_notifications_delivery_queue"
NEW = "ix_notifications_delivery_queue_active"


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {OLD}")
        op.execute(
            f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {NEW} "
            "ON notifications (next_attempt_at, created_at) "
            "WHERE status IN ('queued','processing')"
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {NEW}")
        op.execute(
            f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {OLD} "
            "ON notifications (status, next_attempt_at, created_at)"
        )
