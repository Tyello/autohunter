"""operational io indexes

Revision ID: a1b2c3d4e5f6
Revises: 7a9b8c6d5e4f
Create Date: 2026-05-04 00:00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = '7a9b8c6d5e4f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == 'postgresql':
        with op.get_context().autocommit_block():
            op.execute("CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_system_logs_created_level_event_type ON system_logs (created_at DESC, level, event_type)")
            op.execute("CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_system_logs_created_source_fingerprint ON system_logs (created_at DESC, source, fingerprint)")
            op.execute("CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_source_runs_source_created_status ON source_runs (source, created_at DESC, status)")
    else:
        op.create_index('ix_system_logs_created_level_event_type', 'system_logs', ['created_at', 'level', 'event_type'], unique=False)
        op.create_index('ix_system_logs_created_source_fingerprint', 'system_logs', ['created_at', 'source', 'fingerprint'], unique=False)
        op.create_index('ix_source_runs_source_created_status', 'source_runs', ['source', 'created_at', 'status'], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == 'postgresql':
        with op.get_context().autocommit_block():
            op.execute('DROP INDEX CONCURRENTLY IF EXISTS ix_source_runs_source_created_status')
            op.execute('DROP INDEX CONCURRENTLY IF EXISTS ix_system_logs_created_source_fingerprint')
            op.execute('DROP INDEX CONCURRENTLY IF EXISTS ix_system_logs_created_level_event_type')
    else:
        op.drop_index('ix_source_runs_source_created_status', table_name='source_runs')
        op.drop_index('ix_system_logs_created_source_fingerprint', table_name='system_logs')
        op.drop_index('ix_system_logs_created_level_event_type', table_name='system_logs')
