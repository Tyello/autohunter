"""telemetry events and structured log fields

Revision ID: b7c1c9a0d8e0
Revises: f3a9c37c2d1b
Create Date: 2026-02-02

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "b7c1c9a0d8e0"
down_revision: Union[str, Sequence[str], None] = "f3a9c37c2d1b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # gen_random_uuid() comes from pgcrypto
    op.execute("create extension if not exists pgcrypto;")

    # 1) Extend system_logs for structured querying (optional fields)
    op.add_column("system_logs", sa.Column("source", sa.Text(), nullable=True))
    op.add_column("system_logs", sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("system_logs", sa.Column("event_type", sa.Text(), nullable=True))
    op.add_column("system_logs", sa.Column("fingerprint", sa.Text(), nullable=True))
    op.add_column("system_logs", sa.Column("tags", postgresql.ARRAY(sa.Text()), nullable=True))

    op.create_foreign_key(
        "fk_system_logs_run_id_source_runs",
        "system_logs",
        "source_runs",
        ["run_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # NOTE: some deployments already have a created_at index on system_logs.
    # Use IF NOT EXISTS to make the migration safe to run on upgraded databases.
    op.execute("CREATE INDEX IF NOT EXISTS ix_system_logs_created_at ON system_logs (created_at)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_system_logs_source_created_at ON system_logs (source, created_at)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_system_logs_event_type_created_at ON system_logs (event_type, created_at)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_system_logs_fingerprint_created_at ON system_logs (fingerprint, created_at)")

    # 2) Extend source_runs (execution shape + runtime snapshot)
    op.add_column("source_runs", sa.Column("groups", sa.Integer(), nullable=True))
    op.add_column("source_runs", sa.Column("wishlists", sa.Integer(), nullable=True))
    op.add_column("source_runs", sa.Column("proxy_server", sa.Text(), nullable=True))
    op.add_column("source_runs", sa.Column("browser_fallback_enabled", sa.Boolean(), nullable=True))
    op.add_column("source_runs", sa.Column("force_browser", sa.Boolean(), nullable=True))

    op.execute("CREATE INDEX IF NOT EXISTS ix_source_runs_source_created_at ON source_runs (source, created_at)")

    # 3) New: telemetry_events (high-signal structured events)
    op.create_table(
        "telemetry_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("level", sa.Text(), nullable=False, server_default=sa.text("'info'")),
        sa.Column("source", sa.Text(), nullable=True),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("wishlist_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("account_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("fingerprint", sa.Text(), nullable=False),
        sa.Column("tags", postgresql.ARRAY(sa.Text()), nullable=True),
        sa.Column("evidence", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    op.create_foreign_key(
        "fk_telemetry_events_run_id_source_runs",
        "telemetry_events",
        "source_runs",
        ["run_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_telemetry_events_wishlist_id_wishlists",
        "telemetry_events",
        "wishlists",
        ["wishlist_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_telemetry_events_user_id_users",
        "telemetry_events",
        "users",
        ["user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_telemetry_events_account_id_accounts",
        "telemetry_events",
        "accounts",
        ["account_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.create_index("ix_telemetry_events_created_at", "telemetry_events", ["created_at"])
    op.create_index("ix_telemetry_events_source_created_at", "telemetry_events", ["source", "created_at"])
    op.create_index("ix_telemetry_events_event_type_created_at", "telemetry_events", ["event_type", "created_at"])
    op.create_index("ix_telemetry_events_fingerprint_created_at", "telemetry_events", ["fingerprint", "created_at"])
    op.create_index("ix_telemetry_events_source_event_fingerprint", "telemetry_events", ["source", "event_type", "fingerprint"])

    op.execute(
        """
        create trigger telemetry_events_updated_at
        before update on telemetry_events
        for each row
        execute function update_updated_at();
        """
    )


def downgrade() -> None:
    op.execute("drop trigger if exists telemetry_events_updated_at on telemetry_events;")
    op.drop_index("ix_telemetry_events_source_event_fingerprint", table_name="telemetry_events")
    op.drop_index("ix_telemetry_events_fingerprint_created_at", table_name="telemetry_events")
    op.drop_index("ix_telemetry_events_event_type_created_at", table_name="telemetry_events")
    op.drop_index("ix_telemetry_events_source_created_at", table_name="telemetry_events")
    op.drop_index("ix_telemetry_events_created_at", table_name="telemetry_events")
    op.drop_constraint("fk_telemetry_events_account_id_accounts", "telemetry_events", type_="foreignkey")
    op.drop_constraint("fk_telemetry_events_user_id_users", "telemetry_events", type_="foreignkey")
    op.drop_constraint("fk_telemetry_events_wishlist_id_wishlists", "telemetry_events", type_="foreignkey")
    op.drop_constraint("fk_telemetry_events_run_id_source_runs", "telemetry_events", type_="foreignkey")
    op.drop_table("telemetry_events")

    op.execute("DROP INDEX IF EXISTS ix_source_runs_source_created_at")
    op.drop_column("source_runs", "force_browser")
    op.drop_column("source_runs", "browser_fallback_enabled")
    op.drop_column("source_runs", "proxy_server")
    op.drop_column("source_runs", "wishlists")
    op.drop_column("source_runs", "groups")

    op.execute("DROP INDEX IF EXISTS ix_system_logs_fingerprint_created_at")
    op.execute("DROP INDEX IF EXISTS ix_system_logs_event_type_created_at")
    op.execute("DROP INDEX IF EXISTS ix_system_logs_source_created_at")
    op.execute("DROP INDEX IF EXISTS ix_system_logs_created_at")
    op.drop_constraint("fk_system_logs_run_id_source_runs", "system_logs", type_="foreignkey")
    op.drop_column("system_logs", "tags")
    op.drop_column("system_logs", "fingerprint")
    op.drop_column("system_logs", "event_type")
    op.drop_column("system_logs", "run_id")
    op.drop_column("system_logs", "source")
