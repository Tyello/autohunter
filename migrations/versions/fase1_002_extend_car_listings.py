"""extend car_listings with extras, raw_payload and common fields

Revision ID: fase1_002_car_listings
Revises: fase1_001_source_configs
Create Date: 2026-02-07

Adiciona campos extensíveis e comuns:
- extras (JSONB) para campos específicos da fonte
- raw_payload (JSONB) para debug/reprocessamento
- listing_type (marketplace|auction_lot|classified)
- year, mileage_km, make, model, etc
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'fase1_002_car_listings'
down_revision = 'fase1_001_source_configs'
branch_labels = None
depends_on = None


def upgrade():
    # Campos extensíveis
    op.add_column('car_listings',
        sa.Column('extras', postgresql.JSONB(astext_type=sa.Text()), 
                  nullable=False, server_default='{}')
    )
    
    op.add_column('car_listings',
        sa.Column('raw_payload', postgresql.JSONB(astext_type=sa.Text()), 
                  nullable=True)
    )
    
    # Tipo de listing
    op.add_column('car_listings',
        sa.Column('listing_type', sa.Text(), 
                  nullable=False, server_default='marketplace')
    )
    
    # Rastreabilidade
    op.add_column('car_listings',
        sa.Column('extractor_version', sa.Text(), nullable=True)
    )
    
    # Campos comuns promovidos
    op.add_column('car_listings',
        sa.Column('year', sa.Integer(), nullable=True)
    )
    
    op.add_column('car_listings',
        sa.Column('mileage_km', sa.Integer(), nullable=True)
    )
    
    op.add_column('car_listings',
        sa.Column('fuel_type', sa.Text(), nullable=True)
    )
    
    op.add_column('car_listings',
        sa.Column('transmission', sa.Text(), nullable=True)
    )
    
    op.add_column('car_listings',
        sa.Column('make', sa.Text(), nullable=True)
    )
    
    op.add_column('car_listings',
        sa.Column('model', sa.Text(), nullable=True)
    )
    
    # Índices
    op.create_index(
        'idx_car_listings_listing_type',
        'car_listings',
        ['listing_type']
    )
    
    op.create_index(
        'idx_car_listings_year',
        'car_listings',
        ['year'],
        postgresql_where=sa.text('year IS NOT NULL')
    )
    
    op.create_index(
        'idx_car_listings_make_model',
        'car_listings',
        ['make', 'model'],
        postgresql_where=sa.text('make IS NOT NULL AND model IS NOT NULL')
    )
    
    op.create_index(
        'idx_car_listings_extras',
        'car_listings',
        ['extras'],
        postgresql_using='gin'
    )
    
    # Constraints
    op.create_check_constraint(
        'chk_car_listings_listing_type',
        'car_listings',
        "listing_type IN ('marketplace', 'auction_lot', 'classified')"
    )
    
    op.create_check_constraint(
        'chk_car_listings_fuel_type',
        'car_listings',
        "fuel_type IS NULL OR fuel_type IN ('gasoline', 'ethanol', 'flex', 'diesel', 'electric', 'hybrid')"
    )


def downgrade():
    op.drop_constraint('chk_car_listings_fuel_type', 'car_listings', type_='check')
    op.drop_constraint('chk_car_listings_listing_type', 'car_listings', type_='check')
    
    op.drop_index('idx_car_listings_extras', table_name='car_listings')
    op.drop_index('idx_car_listings_make_model', table_name='car_listings')
    op.drop_index('idx_car_listings_year', table_name='car_listings')
    op.drop_index('idx_car_listings_listing_type', table_name='car_listings')
    
    op.drop_column('car_listings', 'model')
    op.drop_column('car_listings', 'make')
    op.drop_column('car_listings', 'transmission')
    op.drop_column('car_listings', 'fuel_type')
    op.drop_column('car_listings', 'mileage_km')
    op.drop_column('car_listings', 'year')
    op.drop_column('car_listings', 'extractor_version')
    op.drop_column('car_listings', 'listing_type')
    op.drop_column('car_listings', 'raw_payload')
    op.drop_column('car_listings', 'extras')
