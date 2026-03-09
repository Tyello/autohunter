from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.models.scrape_job import ScrapeJob
from app.services.scrape_jobs_service import dequeue_next_job, requeue_stale_running_jobs


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def test_requeue_stale_running_job_and_dequeue(db):
    stale = _utcnow() - timedelta(minutes=40)
    db.add(
        ScrapeJob(
            source="olx",
            queue="http",
            run_at=stale,
            status="running",
            lock_owner="worker-1",
            locked_at=stale,
            started_at=stale,
            attempt=0,
            max_attempts=3,
            priority=0,
        )
    )
    db.commit()

    rescued = requeue_stale_running_jobs(db, queue="http", stale_after_seconds=60)
    assert rescued == 1
    db.commit()

    job = dequeue_next_job(db, queue="http", lock_owner="worker-2")
    assert job is not None
    assert job.source == "olx"
    assert job.status == "running"
    assert job.lock_owner == "worker-2"


def test_recent_running_job_is_not_requeued(db):
    now = _utcnow()
    db.add(
        ScrapeJob(
            source="webmotors",
            queue="browser",
            run_at=now,
            status="running",
            lock_owner="browser-worker",
            locked_at=now - timedelta(seconds=20),
            started_at=now - timedelta(seconds=20),
            attempt=0,
            max_attempts=3,
            priority=0,
        )
    )
    db.commit()

    rescued = requeue_stale_running_jobs(db, queue="browser", stale_after_seconds=300)
    assert rescued == 0

    row = db.query(ScrapeJob).filter(ScrapeJob.source == "webmotors").one()
    assert row.status == "running"
    assert row.lock_owner == "browser-worker"
