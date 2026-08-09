"""add audited monthly fipe update runs

Revision ID: p0_02_fipe_update_runs
Revises: c0f1e2d3a4b5
Create Date: 2026-08-09
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "p0_02_fipe_update_runs"
down_revision = "c0f1e2d3a4b5"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "fipe_update_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("updated_rows", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("reference_month", sa.Text(), nullable=True),
        sa.Column("input_uri", sa.Text(), nullable=True),
        sa.Column("lock_key", sa.Text(), nullable=False, server_default="monthly_fipe_update"),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.CheckConstraint("status IN ('running','completed','failed','skipped')", name="ck_fipe_update_runs_status"),
    )
    op.create_index("ix_fipe_update_runs_started_at", "fipe_update_runs", ["started_at"])
    op.create_index("ix_fipe_update_runs_status_started", "fipe_update_runs", ["status", "started_at"])
    op.create_index("ix_fipe_update_runs_lock_status", "fipe_update_runs", ["lock_key", "status"])


def downgrade():
    op.drop_index("ix_fipe_update_runs_lock_status", table_name="fipe_update_runs")
    op.drop_index("ix_fipe_update_runs_status_started", table_name="fipe_update_runs")
    op.drop_index("ix_fipe_update_runs_started_at", table_name="fipe_update_runs")
    op.drop_table("fipe_update_runs")
