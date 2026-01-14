"""set default uuid for car_listings id

Revision ID: b2c22cf5e571
Revises: c1588953e3d9
Create Date: 2026-01-14 02:36:35.938324

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b2c22cf5e571'
down_revision: Union[str, Sequence[str], None] = 'c1588953e3d9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    op.execute("create extension if not exists pgcrypto;")
    op.execute("alter table car_listings alter column id set default gen_random_uuid();")

def downgrade():
    op.execute("alter table car_listings alter column id drop default;")
