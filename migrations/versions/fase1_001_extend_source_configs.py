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

# revision identifiers
revision = 'fase1_001_source_configs'
down_revision = '<PREVIOUS_REVISION>'  # SUBSTITUIR pela última migration
branch_labels = None
depends_on = None


def upgrade():
    # Adiciona campo extras (JSONB)
    op.add_column('source_configs',
        sa.Column('extra', postgresql.JSONB(astext_type=sa.Text()), 
                  nullable=False, server_default='{}')
    )
    
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
    op.drop_column('source_configs', 'extra')
