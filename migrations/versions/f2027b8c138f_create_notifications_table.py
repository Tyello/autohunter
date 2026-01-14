"""create notifications table

Revision ID: f2027b8c138f
Revises: 2791cc8a94f9
Create Date: 2026-01-13 21:39:16.699138

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f2027b8c138f'
down_revision: Union[str, Sequence[str], None] = '2791cc8a94f9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    op.create_table(
        "notifications",
        sa.Column("id", sa.dialects.postgresql.UUID(), primary_key=True),

        sa.Column("user_id", sa.dialects.postgresql.UUID(),
                  sa.ForeignKey("users.id", ondelete="CASCADE")),
        sa.Column("wishlist_id", sa.dialects.postgresql.UUID(),
                  sa.ForeignKey("wishlists.id", ondelete="CASCADE")),
        sa.Column("car_listing_id", sa.dialects.postgresql.UUID(),
                  sa.ForeignKey("car_listings.id", ondelete="CASCADE")),

        sa.Column("notification_type", sa.Text(), nullable=False),
        # new_listing | price_drop | reappeared

        sa.Column("sent_at", sa.DateTime(timezone=True), server_default=sa.func.now()),

        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now())
    )

    op.execute("""
    create trigger notifications_updated_at
    before update on notifications
    for each row
    execute function update_updated_at();
    """)


def downgrade():
    op.drop_table("notifications")
