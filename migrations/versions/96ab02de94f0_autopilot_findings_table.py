"""autopilot findings table

Revision ID: 96ab02de94f0
Revises: f3a9c37c2d1b
Create Date: 2026-02-02

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "96ab02de94f0"
down_revision: Union[str, Sequence[str], None] = "f3a9c37c2d1b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "autopilot_findings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="open"),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("source", sa.Text(), nullable=True),
        sa.Column("fingerprint", sa.Text(), nullable=False, unique=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("severity", sa.Text(), nullable=False, server_default="warn"),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("hit_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_alert_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("evidence", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("suggested_actions", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_autopilot_findings_source", "autopilot_findings", ["source"])
    op.create_index("ix_autopilot_findings_kind", "autopilot_findings", ["kind"])
    op.create_index("ix_autopilot_findings_last_seen_at", "autopilot_findings", ["last_seen_at"])


def downgrade() -> None:
    op.drop_index("ix_autopilot_findings_last_seen_at", table_name="autopilot_findings")
    op.drop_index("ix_autopilot_findings_kind", table_name="autopilot_findings")
    op.drop_index("ix_autopilot_findings_source", table_name="autopilot_findings")
    op.drop_table("autopilot_findings")
