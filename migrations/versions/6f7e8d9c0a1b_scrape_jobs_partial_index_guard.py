"""ensure scrape_jobs partial unique index for active source+queue

Revision ID: 6f7e8d9c0a1b
Revises: 4c3b2a1f0e9d
Create Date: 2026-05-12
"""

from alembic import op


revision = "6f7e8d9c0a1b"
down_revision = "4c3b2a1f0e9d"
branch_labels = None
depends_on = None


_INDEX_NAME = "ix_scrape_jobs_active_source_queue_unique"


def upgrade():
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.execute(
        f"""
        CREATE UNIQUE INDEX IF NOT EXISTS {_INDEX_NAME}
        ON scrape_jobs (source, queue)
        WHERE status IN ('queued','running');
        """
    )


def downgrade():
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.execute(f"DROP INDEX IF EXISTS {_INDEX_NAME};")
