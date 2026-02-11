"""
Migration: Auction Lots Table

Cria tabela para lotes de leilão (veículos e outros bens).

Revision ID: fase4_002
Revises: fase4_001
Create Date: 2026-02-08
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers
revision = 'fase4_002_auction_lots'
down_revision = 'fase4_001_auction_events'
branch_labels = None
depends_on = None


def upgrade():
    """Cria tabela auction_lots."""
    
    op.create_table(
        'auction_lots',
        
        # Primary Key
        sa.Column('id', sa.Integer(), nullable=False),
        
        # Relação com evento
        sa.Column('event_id', sa.Integer(), nullable=True,
                  comment='FK para auction_events (pode ser NULL se evento não rastreado)'),
        
        # Identificação do lote
        sa.Column('external_id', sa.String(255), nullable=False, index=True,
                  comment='ID externo do lote (ex: "sodre-lote-456")'),
        sa.Column('source', sa.String(100), nullable=False, index=True,
                  comment='Fonte do leilão'),
        sa.Column('lot_number', sa.String(50), nullable=True,
                  comment='Número do lote (ex: "123", "A-456")'),
        
        # Informações básicas
        sa.Column('title', sa.Text(), nullable=False,
                  comment='Título do lote'),
        sa.Column('description', sa.Text(), nullable=True,
                  comment='Descrição detalhada'),
        sa.Column('url', sa.Text(), nullable=False,
                  comment='URL do lote'),
        sa.Column('thumbnail_url', sa.Text(), nullable=True),
        
        # Tipo de bem
        sa.Column('item_type', sa.String(50), nullable=False, index=True,
                  comment='Tipo: vehicle, motorcycle, boat, other'),
        
        # Informações de veículo (se item_type = vehicle)
        sa.Column('make', sa.String(100), nullable=True, index=True,
                  comment='Marca do veículo'),
        sa.Column('model', sa.String(100), nullable=True, index=True,
                  comment='Modelo do veículo'),
        sa.Column('year', sa.Integer(), nullable=True, index=True,
                  comment='Ano do veículo'),
        sa.Column('mileage_km', sa.Integer(), nullable=True,
                  comment='Quilometragem'),
        sa.Column('fuel_type', sa.String(50), nullable=True,
                  comment='Tipo de combustível'),
        sa.Column('transmission', sa.String(50), nullable=True,
                  comment='Transmissão'),
        sa.Column('color', sa.String(50), nullable=True,
                  comment='Cor'),
        sa.Column('plate', sa.String(20), nullable=True,
                  comment='Placa (se disponível)'),
        sa.Column('chassis', sa.String(50), nullable=True,
                  comment='Chassi (se disponível)'),
        
        # Valores e lances
        sa.Column('initial_bid', sa.Numeric(12, 2), nullable=True,
                  comment='Lance inicial'),
        sa.Column('current_bid', sa.Numeric(12, 2), nullable=True,
                  comment='Lance atual (se online)'),
        sa.Column('minimum_bid', sa.Numeric(12, 2), nullable=True,
                  comment='Lance mínimo'),
        sa.Column('estimated_value', sa.Numeric(12, 2), nullable=True,
                  comment='Valor estimado/avaliação'),
        sa.Column('reserve_price', sa.Numeric(12, 2), nullable=True,
                  comment='Preço de reserva (se divulgado)'),
        sa.Column('currency', sa.String(3), server_default='BRL', nullable=False),
        
        # Incremento de lance
        sa.Column('bid_increment', sa.Numeric(12, 2), nullable=True,
                  comment='Incremento mínimo de lance'),
        
        # Número de lances
        sa.Column('total_bids', sa.Integer(), nullable=True,
                  comment='Total de lances recebidos'),
        
        # Status do lote
        sa.Column('status', sa.String(50), nullable=False, index=True,
                  comment='Status: scheduled, live, sold, unsold, cancelled'),
        
        # Localização do bem
        sa.Column('location', sa.Text(), nullable=True,
                  comment='Onde o bem está localizado'),
        sa.Column('city', sa.String(255), nullable=True, index=True),
        sa.Column('state', sa.String(2), nullable=True, index=True),
        
        # Condição
        sa.Column('condition', sa.String(50), nullable=True,
                  comment='Condição: new, used, damaged, salvage'),
        sa.Column('condition_notes', sa.Text(), nullable=True,
                  comment='Notas sobre condição/defeitos'),
        
        # Documentação
        sa.Column('has_documentation', sa.Boolean(), nullable=True,
                  comment='Possui documentação completa?'),
        sa.Column('documentation_notes', sa.Text(), nullable=True,
                  comment='Detalhes sobre documentação'),
        
        # Débitos
        sa.Column('has_debts', sa.Boolean(), nullable=True,
                  comment='Possui débitos/ônus?'),
        sa.Column('debt_amount', sa.Numeric(12, 2), nullable=True,
                  comment='Valor aproximado de débitos'),
        sa.Column('debt_notes', sa.Text(), nullable=True,
                  comment='Detalhes sobre débitos'),
        
        # Visitação
        sa.Column('viewing_available', sa.Boolean(), nullable=True,
                  comment='Visitação disponível?'),
        sa.Column('viewing_location', sa.Text(), nullable=True,
                  comment='Local de visitação'),
        sa.Column('viewing_notes', sa.Text(), nullable=True,
                  comment='Instruções para visitação'),
        
        # Imagens
        sa.Column('image_count', sa.Integer(), nullable=True,
                  comment='Quantidade de imagens disponíveis'),
        sa.Column('images', postgresql.ARRAY(sa.Text()), nullable=True,
                  comment='URLs das imagens'),
        
        # Extras (JSONB flexível)
        sa.Column('extras', postgresql.JSONB(astext_type=sa.Text()), nullable=True,
                  comment='Dados extras em formato JSON'),
        
        # Payload original
        sa.Column('raw_payload', postgresql.JSONB(astext_type=sa.Text()), nullable=True,
                  comment='Dados brutos do scraper'),
        
        # Metadados
        sa.Column('extractor_version', sa.String(50), nullable=True),
        sa.Column('first_seen_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('last_seen_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        
        # Constraints
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['event_id'], ['auction_events.id'], ondelete='SET NULL'),
        sa.UniqueConstraint('source', 'external_id', name='uq_auction_lots_source_external_id'),
    )
    
    # Índices adicionais
    op.create_index('ix_auction_lots_event_id', 'auction_lots', ['event_id'])
    op.create_index('ix_auction_lots_status', 'auction_lots', ['status'])
    op.create_index('ix_auction_lots_item_type', 'auction_lots', ['item_type'])
    op.create_index('ix_auction_lots_make_model', 'auction_lots', ['make', 'model'])
    op.create_index('ix_auction_lots_initial_bid', 'auction_lots', ['initial_bid'])
    op.create_index('ix_auction_lots_created_at', 'auction_lots', ['created_at'])
    
    # Índice composto para busca
    op.create_index('ix_auction_lots_type_status_city', 'auction_lots', 
                    ['item_type', 'status', 'city'])


def downgrade():
    """Remove tabela auction_lots."""
    op.drop_table('auction_lots')
