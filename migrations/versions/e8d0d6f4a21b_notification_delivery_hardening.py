"""notification delivery hardening

Revision ID: e8d0d6f4a21b
Revises: c4f7a8b9d102
Create Date: 2026-03-10 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "e8d0d6f4a21b"
down_revision: Union[str, Sequence[str], None] = "c4f7a8b9d102"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("notifications", sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("notifications", sa.Column("processing_started_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("notifications", sa.Column("processing_owner", sa.Text(), nullable=True))
    op.add_column("notifications", sa.Column("attempts", sa.Integer(), nullable=False, server_default=sa.text("0")))
    op.add_column("notifications", sa.Column("max_attempts", sa.Integer(), nullable=False, server_default=sa.text("3")))

    op.execute("UPDATE notifications SET next_attempt_at = created_at WHERE next_attempt_at IS NULL")

    op.create_index(
        "ix_notifications_delivery_queue",
        "notifications",
        ["status", "next_attempt_at", "created_at"],
    )
    op.create_index("ix_notifications_processing_started_at", "notifications", ["processing_started_at"])


def downgrade() -> None:
    op.drop_index("ix_notifications_processing_started_at", table_name="notifications")
    op.drop_index("ix_notifications_delivery_queue", table_name="notifications")

    op.drop_column("notifications", "max_attempts")
    op.drop_column("notifications", "attempts")
    op.drop_column("notifications", "processing_owner")
    op.drop_column("notifications", "processing_started_at")
    op.drop_column("notifications", "next_attempt_at")
