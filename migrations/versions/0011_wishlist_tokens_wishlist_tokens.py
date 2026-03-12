"""create wishlist_tokens index table

Revision ID: 0011_wishlist_tokens
Revises: 0010_merge_heads
Create Date: 2026-02-28 00:00:01.000000

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "0011_wishlist_tokens"
down_revision = "0010_merge_heads"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "wishlist_tokens",
        sa.Column("wishlist_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("token", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("wishlist_id", "token", name="pk_wishlist_tokens"),
        sa.ForeignKeyConstraint(["wishlist_id"], ["wishlists.id"], ondelete="RESTRICT", name="fk_wishlist_tokens_wishlist_id"),
    )
    # Fast lookup: token -> wishlists
    op.create_index("ix_wishlist_tokens_token", "wishlist_tokens", ["token"], unique=False)
    # Fast cleanup / joins by wishlist_id
    op.create_index("ix_wishlist_tokens_wishlist_id", "wishlist_tokens", ["wishlist_id"], unique=False)


def downgrade():
    op.drop_index("ix_wishlist_tokens_wishlist_id", table_name="wishlist_tokens")
    op.drop_index("ix_wishlist_tokens_token", table_name="wishlist_tokens")
    op.drop_table("wishlist_tokens")
