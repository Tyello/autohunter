"""fipe monthly staging tables

Revision ID: c0f1e2d3a4b5
Revises: 9b1f4d2a7c11
Create Date: 2026-05-26
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "c0f1e2d3a4b5"
down_revision = "9b1f4d2a7c11"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "fipe_sync_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("reference_month", sa.Text(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rows_seen", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rows_inserted", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rows_updated", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("status IN ('pending','running','completed','failed')", name="ck_fipe_sync_runs_status"),
        sa.CheckConstraint("reference_month ~ '^[0-9]{4}-(0[1-9]|1[0-2])$'", name="ck_fipe_sync_runs_reference_month"),
    )
    op.create_table(
        "fipe_catalog_entries",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("reference_month", sa.Text(), nullable=False),
        sa.Column("vehicle_type", sa.Text(), nullable=False, server_default="car"),
        sa.Column("brand_code", sa.Text(), nullable=True),
        sa.Column("brand_name", sa.Text(), nullable=True),
        sa.Column("model_code", sa.Text(), nullable=True),
        sa.Column("model_name", sa.Text(), nullable=False),
        sa.Column("year_code", sa.Text(), nullable=True),
        sa.Column("model_year", sa.Integer(), nullable=True),
        sa.Column("fuel", sa.Text(), nullable=True),
        sa.Column("fipe_code", sa.Text(), nullable=True),
        sa.Column("price", sa.Numeric(12, 2), nullable=False),
        sa.Column("currency", sa.Text(), nullable=False, server_default="BRL"),
        sa.Column("raw_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("reference_month ~ '^[0-9]{4}-(0[1-9]|1[0-2])$'", name="ck_fipe_catalog_entries_reference_month"),
        sa.UniqueConstraint("reference_month", "vehicle_type", "brand_code", "model_code", "year_code", "source", name="uq_fipe_catalog_entries_key"),
    )
    op.create_index("ix_fipe_catalog_month_type", "fipe_catalog_entries", ["reference_month", "vehicle_type"])
    op.create_index("ix_fipe_catalog_brand_model_year", "fipe_catalog_entries", ["brand_name", "model_name", "model_year"])
    op.create_index("ix_fipe_catalog_fipe_code", "fipe_catalog_entries", ["fipe_code"])


def downgrade() -> None:
    op.drop_index("ix_fipe_catalog_fipe_code", table_name="fipe_catalog_entries")
    op.drop_index("ix_fipe_catalog_brand_model_year", table_name="fipe_catalog_entries")
    op.drop_index("ix_fipe_catalog_month_type", table_name="fipe_catalog_entries")
    op.drop_table("fipe_catalog_entries")
    op.drop_table("fipe_sync_runs")
