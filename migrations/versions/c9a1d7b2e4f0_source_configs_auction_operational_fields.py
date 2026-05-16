"""source_configs auction operational fields

Revision ID: c9a1d7b2e4f0
Revises: fed869eabd8b
Create Date: 2026-05-16
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision: str = "c9a1d7b2e4f0"
down_revision: Union[str, Sequence[str], None] = "fed869eabd8b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_column(table: str, col: str) -> bool:
    bind = op.get_bind()
    insp = inspect(bind)
    return any(c["name"] == col for c in insp.get_columns(table))


def upgrade() -> None:
    if not _has_column("source_configs", "source_type"):
        op.add_column("source_configs", sa.Column("source_type", sa.Text(), nullable=False, server_default=sa.text("'classified'")))
    if not _has_column("source_configs", "user_eligible"):
        op.add_column("source_configs", sa.Column("user_eligible", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    if not _has_column("source_configs", "admin_only"):
        op.add_column("source_configs", sa.Column("admin_only", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    if not _has_column("source_configs", "status"):
        op.add_column("source_configs", sa.Column("status", sa.Text(), nullable=True))


def downgrade() -> None:
    if _has_column("source_configs", "status"):
        op.drop_column("source_configs", "status")
    if _has_column("source_configs", "admin_only"):
        op.drop_column("source_configs", "admin_only")
    if _has_column("source_configs", "user_eligible"):
        op.drop_column("source_configs", "user_eligible")
    if _has_column("source_configs", "source_type"):
        op.drop_column("source_configs", "source_type")
