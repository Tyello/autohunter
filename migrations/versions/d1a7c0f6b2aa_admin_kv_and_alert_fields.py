"""admin kv + alert fields

Revision ID: d1a7c0f6b2aa
Revises: ec4a5f769526
Create Date: 2026-01-27

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "d1a7c0f6b2aa"
down_revision: Union[str, Sequence[str], None] = "ec4a5f769526"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "app_kv",
        sa.Column("key", sa.Text(), primary_key=True),
        sa.Column("value", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.execute(
        """
        create trigger app_kv_updated_at
        before update on app_kv
        for each row
        execute function update_updated_at();
        """
    )

    op.add_column("source_states", sa.Column("last_admin_alert_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("source_states", sa.Column("last_admin_alert_status", sa.Text(), nullable=True))
    op.add_column("source_states", sa.Column("last_admin_alert_error_hash", sa.Text(), nullable=True))

    # proteção adicional no banco: starts_at default now()
    op.alter_column("subscriptions", "starts_at", server_default=sa.text("now()"))


def downgrade() -> None:
    op.alter_column("subscriptions", "starts_at", server_default=None)

    op.drop_column("source_states", "last_admin_alert_error_hash")
    op.drop_column("source_states", "last_admin_alert_status")
    op.drop_column("source_states", "last_admin_alert_at")

    op.execute("drop trigger if exists app_kv_updated_at on app_kv;")
    op.drop_table("app_kv")
