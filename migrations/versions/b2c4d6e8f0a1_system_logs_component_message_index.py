"""system_logs component+message index (heartbeat lookup)

Revision ID: b2c4d6e8f0a1
Revises: p0_03_supabase_io_indexes
Create Date: 2026-08-10 00:00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'b2c4d6e8f0a1'
down_revision: Union[str, Sequence[str], None] = 'p0_03_supabase_io_indexes'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == 'postgresql':
        with op.get_context().autocommit_block():
            op.execute("CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_system_logs_component_message_created_at ON system_logs (component, message, created_at DESC)")
    else:
        op.create_index('ix_system_logs_component_message_created_at', 'system_logs', ['component', 'message', 'created_at'], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == 'postgresql':
        with op.get_context().autocommit_block():
            op.execute('DROP INDEX CONCURRENTLY IF EXISTS ix_system_logs_component_message_created_at')
    else:
        op.drop_index('ix_system_logs_component_message_created_at', table_name='system_logs')
