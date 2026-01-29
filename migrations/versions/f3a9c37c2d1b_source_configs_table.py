"""source configs table

Revision ID: f3a9c37c2d1b
Revises: 01a6af3ccdcd
Create Date: 2026-01-28

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "f3a9c37c2d1b"
down_revision: Union[str, Sequence[str], None] = "01a6af3ccdcd"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # gen_random_uuid() vem do pgcrypto
    op.execute("create extension if not exists pgcrypto;")

    op.create_table(
        "source_configs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("source", sa.Text(), nullable=False, unique=True),
        sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("sched_minutes", sa.Integer(), nullable=False, server_default=sa.text("60")),
        sa.Column("cooldown_minutes", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("rate_limit_seconds", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("proxy_server", sa.Text(), nullable=True),
        sa.Column("browser_fallback_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("force_browser", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("extra", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    op.execute(
        """
        create trigger source_configs_updated_at
        before update on source_configs
        for each row
        execute function update_updated_at();
        """
    )

    # schedule dinâmico por DB
    op.add_column("source_states", sa.Column("last_effective_run_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_source_states_last_effective_run_at", "source_states", ["last_effective_run_at"])


def downgrade() -> None:
    op.drop_index("ix_source_states_last_effective_run_at", table_name="source_states")
    op.drop_column("source_states", "last_effective_run_at")

    op.execute("drop trigger if exists source_configs_updated_at on source_configs;")
    op.drop_table("source_configs")
