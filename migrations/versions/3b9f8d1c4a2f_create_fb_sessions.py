"""create fb_sessions

Revision ID: 3b9f8d1c4a2f
Revises: 0011_wishlist_tokens, fase1_006_score_v2
Create Date: 2026-03-01 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = '3b9f8d1c4a2f'
down_revision = ('0011_wishlist_tokens', 'fase1_006_score_v2')
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'fb_sessions',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('user_id', sa.Text(), nullable=False),
        sa.Column('pairing_code', sa.Text(), nullable=True),
        sa.Column('pairing_expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('pairing_used_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('status', sa.Text(), nullable=False),
        sa.Column('profile_dir', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('session_validated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_check_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_ok_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_error_kind', sa.Text(), nullable=True),
        sa.Column('last_error_message', sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id'),
    )
    op.create_index(op.f('ix_fb_sessions_user_id'), 'fb_sessions', ['user_id'], unique=True)
    op.create_index(op.f('ix_fb_sessions_pairing_code'), 'fb_sessions', ['pairing_code'], unique=False)
    op.create_index(op.f('ix_fb_sessions_status'), 'fb_sessions', ['status'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_fb_sessions_status'), table_name='fb_sessions')
    op.drop_index(op.f('ix_fb_sessions_pairing_code'), table_name='fb_sessions')
    op.drop_index(op.f('ix_fb_sessions_user_id'), table_name='fb_sessions')
    op.drop_table('fb_sessions')
