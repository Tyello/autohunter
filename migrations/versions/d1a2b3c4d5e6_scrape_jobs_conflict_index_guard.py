"""guard scrape_jobs conflict index for scheduler enqueue

Revision ID: d1a2b3c4d5e6
Revises: c3d4e5f6a7b8
Create Date: 2026-03-15
"""

from alembic import op


revision = "d1a2b3c4d5e6"
down_revision = "c3d4e5f6a7b8"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        """
        create unique index if not exists uq_scrape_jobs_active_source_queue
        on scrape_jobs (source, queue)
        where status IN ('queued','running');
        """
    )


def downgrade():
    op.execute("drop index if exists uq_scrape_jobs_active_source_queue;")
