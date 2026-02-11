"""
Migration: Auction Events Table

Cria tabela para eventos/sessões de leilão.

Revision ID: fase4_001
Revises: <PREVIOUS_REVISION>
Create Date: 2026-02-08
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers
revision = 'fase4_001_auction_events'
down_revision = '<PREVIOUS_REVISION>'  # Substituir pelo último revision da Fase 1
branch_labels = None
depends_on = None


def upgrade():
    """Cria tabela auction_events."""
    
    op.create_table(
        'auction_events',
        
        # Primary Key
        sa.Column('id', sa.Integer(), nullable=False),
        
        # Identificação do evento
        sa.Column('external_id', sa.String(255), nullable=False, index=True, 
                  comment='ID externo do evento (ex: "sodre-123")'),
        sa.Column('source', sa.String(100), nullable=False, index=True,
                  comment='Fonte do leilão (ex: "sodre_santoro")'),
        
        # Informações básicas
        sa.Column('title', sa.Text(), nullable=False,
                  comment='Título do evento (ex: "Leilão de Veículos - Janeiro 2026")'),
        sa.Column('description', sa.Text(), nullable=True,
                  comment='Descrição do evento'),
        sa.Column('url', sa.Text(), nullable=False,
                  comment='URL do evento'),
        
        # Datas e horários
        sa.Column('event_date', sa.DateTime(timezone=True), nullable=True,
                  comment='Data/hora do leilão'),
        sa.Column('registration_deadline', sa.DateTime(timezone=True), nullable=True,
                  comment='Prazo para cadastro/habilitação'),
        sa.Column('viewing_start', sa.DateTime(timezone=True), nullable=True,
                  comment='Início do período de visitação'),
        sa.Column('viewing_end', sa.DateTime(timezone=True), nullable=True,
                  comment='Fim do período de visitação'),
        
        # Status
        sa.Column('status', sa.String(50), nullable=False, index=True,
                  comment='Status: scheduled, live, ended, cancelled'),
        
        # Localização
        sa.Column('location', sa.Text(), nullable=True,
                  comment='Local do evento'),
        sa.Column('city', sa.String(255), nullable=True, index=True),
        sa.Column('state', sa.String(2), nullable=True, index=True),
        
        # Estatísticas
        sa.Column('total_lots', sa.Integer(), nullable=True,
                  comment='Total de lotes no evento'),
        sa.Column('vehicle_lots', sa.Integer(), nullable=True,
                  comment='Lotes de veículos'),
        
        # Tipo de leilão
        sa.Column('auction_type', sa.String(50), nullable=True,
                  comment='Tipo: judicial, extrajudicial, government, etc'),
        sa.Column('modality', sa.String(50), nullable=True,
                  comment='Modalidade: online, presencial, hibrido'),
        
        # Organização
        sa.Column('auctioneer', sa.String(255), nullable=True,
                  comment='Leiloeiro responsável'),
        sa.Column('organizer', sa.String(255), nullable=True,
                  comment='Empresa organizadora'),
        
        # Extras (JSONB flexível)
        sa.Column('extras', postgresql.JSONB(astext_type=sa.Text()), nullable=True,
                  comment='Dados extras em formato JSON'),
        
        # Payload original
        sa.Column('raw_payload', postgresql.JSONB(astext_type=sa.Text()), nullable=True,
                  comment='Dados brutos do scraper'),
        
        # Metadados
        sa.Column('extractor_version', sa.String(50), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        
        # Constraints
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('source', 'external_id', name='uq_auction_events_source_external_id'),
    )
    
    # Índices adicionais
    op.create_index('ix_auction_events_event_date', 'auction_events', ['event_date'])
    op.create_index('ix_auction_events_status_event_date', 'auction_events', ['status', 'event_date'])
    op.create_index('ix_auction_events_created_at', 'auction_events', ['created_at'])


def downgrade():
    """Remove tabela auction_events."""
    op.drop_table('auction_events')
