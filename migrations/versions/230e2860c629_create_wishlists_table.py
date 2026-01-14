"""create wishlists table

Revision ID: 230e2860c629
Revises: dd6542891141
Create Date: 2026-01-13 21:33:15.814559

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '230e2860c629'
down_revision: Union[str, Sequence[str], None] = 'dd6542891141'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    op.create_table(
        "wishlists",
        sa.Column("id", sa.dialects.postgresql.UUID(), primary_key=True),
        sa.Column("user_id", sa.dialects.postgresql.UUID(), sa.ForeignKey("users.id", ondelete="CASCADE")),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true"),

        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now())
    )

    op.execute("""
    create trigger wishlists_updated_at
    before update on wishlists
    for each row
    execute function update_updated_at();
    """)


def downgrade() -> None:
    """Downgrade schema."""
    pass
