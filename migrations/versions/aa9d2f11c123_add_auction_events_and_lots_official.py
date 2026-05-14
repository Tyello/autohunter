"""add auction events and lots official

Revision ID: aa9d2f11c123
Revises: 7b9e1c2d3f4a
Create Date: 2026-05-13
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'aa9d2f11c123'
down_revision = '7b9e1c2d3f4a'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'auction_events',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column('source', sa.Text(), nullable=False),
        sa.Column('external_id', sa.Text(), nullable=False),
        sa.Column('title', sa.Text(), nullable=True),
        sa.Column('url', sa.Text(), nullable=True),
        sa.Column('event_date', sa.DateTime(timezone=True), nullable=True),
        sa.Column('status', sa.Text(), nullable=False, server_default='unknown'),
        sa.Column('city', sa.Text(), nullable=True),
        sa.Column('state', sa.Text(), nullable=True),
        sa.Column('auction_type', sa.Text(), nullable=True),
        sa.Column('modality', sa.Text(), nullable=True),
        sa.Column('auctioneer', sa.Text(), nullable=True),
        sa.Column('organizer', sa.Text(), nullable=True),
        sa.Column('total_lots', sa.Integer(), nullable=True),
        sa.Column('vehicle_lots', sa.Integer(), nullable=True),
        sa.Column('extras', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('raw_payload', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('uq_auction_events_source_external_id', 'auction_events', ['source', 'external_id'], unique=True)
    op.create_index('ix_auction_events_source_status', 'auction_events', ['source', 'status'])

    op.create_table(
        'auction_lots',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column('event_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('auction_events.id', ondelete='SET NULL'), nullable=True),
        sa.Column('source', sa.Text(), nullable=False),
        sa.Column('external_id', sa.Text(), nullable=False),
        sa.Column('lot_number', sa.Text(), nullable=True),
        sa.Column('title', sa.Text(), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('url', sa.Text(), nullable=True),
        sa.Column('thumbnail_url', sa.Text(), nullable=True),
        sa.Column('item_type', sa.Text(), nullable=False, server_default='other'),
        sa.Column('make', sa.Text(), nullable=True), sa.Column('model', sa.Text(), nullable=True), sa.Column('version', sa.Text(), nullable=True),
        sa.Column('year', sa.Integer(), nullable=True), sa.Column('mileage_km', sa.Integer(), nullable=True), sa.Column('fuel_type', sa.Text(), nullable=True),
        sa.Column('transmission', sa.Text(), nullable=True), sa.Column('color', sa.Text(), nullable=True),
        sa.Column('city', sa.Text(), nullable=True), sa.Column('state', sa.Text(), nullable=True), sa.Column('location', sa.Text(), nullable=True),
        sa.Column('initial_bid', sa.Numeric(14, 2), nullable=True), sa.Column('current_bid', sa.Numeric(14, 2), nullable=True), sa.Column('bid_increment', sa.Numeric(14, 2), nullable=True),
        sa.Column('total_bids', sa.Integer(), nullable=True), sa.Column('status', sa.Text(), nullable=False, server_default='unknown'),
        sa.Column('auction_start_at', sa.DateTime(timezone=True), nullable=True), sa.Column('auction_end_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('condition', sa.Text(), nullable=True), sa.Column('document_type', sa.Text(), nullable=True), sa.Column('condition_notes', sa.Text(), nullable=True),
        sa.Column('has_documentation', sa.Boolean(), nullable=True), sa.Column('has_debts', sa.Boolean(), nullable=True),
        sa.Column('image_count', sa.Integer(), nullable=True), sa.Column('images', postgresql.ARRAY(sa.Text()), nullable=True),
        sa.Column('extras', postgresql.JSONB(astext_type=sa.Text()), nullable=True), sa.Column('raw_payload', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('first_seen_at', sa.DateTime(timezone=True), nullable=False), sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False), sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('uq_auction_lots_source_external_id', 'auction_lots', ['source', 'external_id'], unique=True)
    op.create_index('ix_auction_lots_source_status', 'auction_lots', ['source', 'status'])
    op.create_index('ix_auction_lots_auction_end_at', 'auction_lots', ['auction_end_at'])
    op.create_index('ix_auction_lots_make_model_year', 'auction_lots', ['make', 'model', 'year'])
    op.create_index('ix_auction_lots_item_type_status', 'auction_lots', ['item_type', 'status'])
    op.create_index('ix_auction_lots_city_state', 'auction_lots', ['city', 'state'])


def downgrade() -> None:
    op.drop_table('auction_lots')
    op.drop_table('auction_events')
