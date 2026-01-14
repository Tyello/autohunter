"""create system_logs table

Revision ID: 9007d2952436
Revises: f2027b8c138f
Create Date: 2026-01-13 21:40:05.157457

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9007d2952436'
down_revision: Union[str, Sequence[str], None] = 'f2027b8c138f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    op.create_table(
        "system_logs",
        sa.Column("id", sa.dialects.postgresql.UUID(), primary_key=True),

        sa.Column("level", sa.Text(), nullable=False),
        # INFO | WARNING | ERROR

        sa.Column("source", sa.Text(), nullable=False),
        # scraping_ml | scraping_olx | bot | matcher | scheduler

        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("context", sa.dialects.postgresql.JSONB()),

        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now())
    )

    op.execute("""
    create trigger system_logs_updated_at
    before update on system_logs
    for each row
    execute function update_updated_at();
    """)


def downgrade():
    op.drop_table("system_logs")
