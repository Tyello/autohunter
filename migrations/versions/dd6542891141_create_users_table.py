"""create users table

Revision ID: dd6542891141
Revises: 89ffa2654849
Create Date: 2026-01-13 21:30:56.091027

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'dd6542891141'
down_revision: Union[str, Sequence[str], None] = '89ffa2654849'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    op.create_table(
        "users",
        sa.Column("id", sa.dialects.postgresql.UUID(), primary_key=True),
        sa.Column("telegram_chat_id", sa.BigInteger(), nullable=False, unique=True),
        sa.Column("username", sa.Text()),
        sa.Column("is_active", sa.Boolean(), server_default="true"),

        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now())
    )

    op.execute("""
    create trigger users_updated_at
    before update on users
    for each row
    execute function update_updated_at();
    """)


def downgrade():
    op.drop_table("users")
