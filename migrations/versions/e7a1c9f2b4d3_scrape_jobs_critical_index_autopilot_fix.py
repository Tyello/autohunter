"""ensure canonical scrape_jobs active partial unique index for autopilot

Revision ID: e7a1c9f2b4d3
Revises: c0f1e2d3a4b5
Create Date: 2026-05-28
"""

from alembic import op


revision = "e7a1c9f2b4d3"
down_revision = "c0f1e2d3a4b5"
branch_labels = None
depends_on = None

_CANONICAL_INDEX = "uq_scrape_jobs_active_source_queue"
_LEGACY_INDEX = "ix_scrape_jobs_active_source_queue_unique"


def upgrade():
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    dup = bind.execute(
        """
        select source, queue, count(*) as c
        from scrape_jobs
        where status in ('queued','running')
        group by source, queue
        having count(*) > 1
        limit 1
        """
    ).fetchone()
    if dup:
        raise RuntimeError(
            "Cannot create unique partial index uq_scrape_jobs_active_source_queue: "
            f"active duplicate found for source={dup[0]!r} queue={dup[1]!r} count={int(dup[2])}."
        )

    op.execute(
        f"""
        CREATE UNIQUE INDEX IF NOT EXISTS {_CANONICAL_INDEX}
        ON scrape_jobs (source, queue)
        WHERE status IN ('queued','running');
        """
    )
    op.execute(f"DROP INDEX IF EXISTS {_LEGACY_INDEX};")


def downgrade():
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.execute(f"DROP INDEX IF EXISTS {_CANONICAL_INDEX};")
