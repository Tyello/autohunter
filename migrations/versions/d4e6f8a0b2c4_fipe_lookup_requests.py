"""add fipe lookup requests

Revision ID: d4e6f8a0b2c4
Revises: b2c4d6e8f0a1
Create Date: 2026-08-11
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "d4e6f8a0b2c4"
down_revision = "b2c4d6e8f0a1"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "fipe_lookup_requests",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("wishlist_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("wishlists.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('pending','processing','done','skipped','failed')",
            name="ck_fipe_lookup_requests_status",
        ),
    )
    op.create_index("ix_fipe_lookup_requests_status_created", "fipe_lookup_requests", ["status", "created_at"])


def downgrade():
    op.drop_index("ix_fipe_lookup_requests_status_created", table_name="fipe_lookup_requests")
    op.drop_table("fipe_lookup_requests")
