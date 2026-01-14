"""add updated_at trigger

Revision ID: 89ffa2654849
Revises: 0fa4e64f67ad
Create Date: 2026-01-13 21:30:14.074878

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '89ffa2654849'
down_revision: Union[str, Sequence[str], None] = '0fa4e64f67ad'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    op.execute("""
    create or replace function update_updated_at()
    returns trigger as $$
    begin
      new.updated_at = now();
      return new;
    end;
    $$ language plpgsql;
    """)


def downgrade():
    op.execute("drop function if exists update_updated_at;")
