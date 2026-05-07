"""add subscription period validity fields

Revision ID: 4c3b2a1f0e9d
Revises: 2f4d2d9f8a11
Create Date: 2026-05-07
"""
from alembic import op
import sqlalchemy as sa

revision = '4c3b2a1f0e9d'
down_revision = '2f4d2d9f8a11'
branch_labels = None
depends_on = None


def _has_column(inspector, table: str, column: str) -> bool:
    return any(col['name'] == column for col in inspector.get_columns(table))


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not _has_column(inspector, 'subscriptions', 'current_period_start'):
        op.add_column('subscriptions', sa.Column('current_period_start', sa.DateTime(timezone=True), nullable=True))
    if not _has_column(inspector, 'subscriptions', 'current_period_end'):
        op.add_column('subscriptions', sa.Column('current_period_end', sa.DateTime(timezone=True), nullable=True))
    if not _has_column(inspector, 'subscriptions', 'cancel_at_period_end'):
        op.add_column('subscriptions', sa.Column('cancel_at_period_end', sa.Boolean(), nullable=False, server_default=sa.text('false')))
    if not _has_column(inspector, 'subscriptions', 'metadata'):
        op.add_column('subscriptions', sa.Column('metadata', sa.JSON(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    for col in ('metadata', 'cancel_at_period_end', 'current_period_end', 'current_period_start'):
        if _has_column(inspector, 'subscriptions', col):
            op.drop_column('subscriptions', col)
