"""extend source configs with extras and tunables

Revision ID: fase1_001_source_configs
Revises: <PREVIOUS_REVISION>
Create Date: 2026-02-07

Adiciona campos para configuração granular das fontes:
- extra (JSONB) para tunables específicos
- circuit breaker configs
- fetch_mode (http|browser|hybrid)
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy import inspect, text

# revision identifiers
revision = 'fase1_001_source_configs'
down_revision = 'e695123144b5'  # SUBSTITUIR pela última migration
branch_labels = None
depends_on = None


def _has_column(table: str, col: str, schema: str | None = None) -> bool:
    bind = op.get_bind()
    insp = inspect(bind)
    return any(c["name"] == col for c in insp.get_columns(table, schema=schema))

def _ensure_jsonb_defaults(table: str, col: str):
    # garante default, preenche NULLs e força NOT NULL
    op.execute(text(f"ALTER TABLE {table} ALTER COLUMN {col} SET DEFAULT '{{}}'::jsonb"))
    op.execute(text(f"UPDATE {table} SET {col}='{{}}'::jsonb WHERE {col} IS NULL"))
    op.execute(text(f"ALTER TABLE {table} ALTER COLUMN {col} SET NOT NULL"))

def upgrade():
    # Adiciona campo extras (JSONB)
    if not _has_column("source_configs", "extra"):
        op.add_column('source_configs',
            sa.Column('extra', postgresql.JSONB(astext_type=sa.Text()),
                      nullable=False, server_default='{}')
        )
    else:
        _ensure_jsonb_defaults("source_configs", "extra")
    
    # Índice GIN para busca em extra
    op.create_index(
        'idx_source_configs_extra',
        'source_configs',
        ['extra'],
        postgresql_using='gin'
    )
    
    # Circuit breaker configs
    op.add_column('source_configs',
        sa.Column('circuit_breaker_threshold', sa.Integer(), 
                  nullable=False, server_default='5')
    )
    op.add_column('source_configs',
        sa.Column('circuit_breaker_cooldown_s', sa.Integer(), 
                  nullable=False, server_default='300')
    )
    
    # Fetch mode
    op.add_column('source_configs',
        sa.Column('fetch_mode', sa.Text(), 
                  nullable=False, server_default='http')
    )
    
    # Constraint para fetch_mode
    op.create_check_constraint(
        'chk_source_configs_fetch_mode',
        'source_configs',
        "fetch_mode IN ('http', 'browser', 'hybrid')"
    )


def downgrade():
    op.drop_constraint('chk_source_configs_fetch_mode', 'source_configs', type_='check')
    op.drop_column('source_configs', 'fetch_mode')
    op.drop_column('source_configs', 'circuit_breaker_cooldown_s')
    op.drop_column('source_configs', 'circuit_breaker_threshold')
    op.drop_index('idx_source_configs_extra', table_name='source_configs')
    if _has_column("source_configs", "extra"):
        op.drop_column('source_configs', 'extra')
