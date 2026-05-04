"""operational indexes for logs and source runs

Revision ID: 20260504_01
Revises: fed869eabd8b
Create Date: 2026-05-04
"""
from alembic import op

# revision identifiers, used by Alembic.
revision = '20260504_01'
down_revision = '7a9b8c6d5e4f'
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        with op.get_context().autocommit_block():
            op.execute("CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_system_logs_created_level_event_type ON system_logs (created_at DESC, level, event_type)")
            op.execute("CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_system_logs_created_source_fingerprint ON system_logs (created_at DESC, source, fingerprint)")
            op.execute("CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_source_runs_source_created_status ON source_runs (source, created_at DESC, status)")
    else:
        op.create_index("ix_system_logs_created_level_event_type", "system_logs", ["created_at", "level", "event_type"], unique=False)
        op.create_index("ix_system_logs_created_source_fingerprint", "system_logs", ["created_at", "source", "fingerprint"], unique=False)
        op.create_index("ix_source_runs_source_created_status", "source_runs", ["source", "created_at", "status"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        with op.get_context().autocommit_block():
            op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_source_runs_source_created_status")
            op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_system_logs_created_source_fingerprint")
            op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_system_logs_created_level_event_type")
    else:
        op.drop_index("ix_source_runs_source_created_status", table_name="source_runs")
        op.drop_index("ix_system_logs_created_source_fingerprint", table_name="system_logs")
        op.drop_index("ix_system_logs_created_level_event_type", table_name="system_logs")
