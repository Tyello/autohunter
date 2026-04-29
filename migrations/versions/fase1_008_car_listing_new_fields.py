"""add car listing extended fields

Revision ID: fase1_008_car_listing_new_fields
Revises: fase1_007_car_listings_contract_fields
Create Date: 2026-04-29
"""
from alembic import op
import sqlalchemy as sa

revision = 'fase1_008_car_listing_new_fields'
down_revision = 'fase1_007_car_contract'
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.add_column('car_listings', sa.Column('doors', sa.Integer(), nullable=True))
    op.add_column('car_listings', sa.Column('body_type', sa.Text(), nullable=True))
    op.add_column('car_listings', sa.Column('cross_source_fingerprint', sa.Text(), nullable=True))

def downgrade() -> None:
    op.drop_column('car_listings', 'cross_source_fingerprint')
    op.drop_column('car_listings', 'body_type')
    op.drop_column('car_listings', 'doors')
