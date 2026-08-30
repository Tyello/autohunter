"""car_listings liveness columns status last_seen_at

Revision ID: 211de43e94c3
Revises: f4a8c1d3e7b2
Create Date: 2026-08-29 23:05:55.891006

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '211de43e94c3'
down_revision: Union[str, Sequence[str], None] = 'f4a8c1d3e7b2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('car_listings', sa.Column('status', sa.Text(), nullable=False, server_default='ativo'))
    op.add_column('car_listings', sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')))
    op.create_check_constraint('check_status_valid', 'car_listings', "status IN ('ativo','suspeito','inativo')")


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('check_status_valid', 'car_listings', type_='check')
    op.drop_column('car_listings', 'last_seen_at')
    op.drop_column('car_listings', 'status')
