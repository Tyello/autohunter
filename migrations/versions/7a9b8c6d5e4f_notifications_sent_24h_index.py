"""add notifications sent 24h wishlist index

Revision ID: 7a9b8c6d5e4f
Revises: 1d2e3f4a5b6c
Create Date: 2026-05-02
"""

from alembic import op
import sqlalchemy as sa


revision = "7a9b8c6d5e4f"
down_revision = "1d2e3f4a5b6c"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.create_index(
            "ix_notifications_wishlist_sent_at_sent",
            "notifications",
            ["wishlist_id", "sent_at"],
            unique=False,
            postgresql_where=sa.text("status = 'sent'"),
        )
        return

    op.create_index(
        "ix_notifications_wishlist_status_sent_at",
        "notifications",
        ["wishlist_id", "status", "sent_at"],
        unique=False,
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.drop_index("ix_notifications_wishlist_sent_at_sent", table_name="notifications")
        return

    op.drop_index("ix_notifications_wishlist_status_sent_at", table_name="notifications")
