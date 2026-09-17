from __future__ import annotations

from datetime import datetime, timezone

from app.models.scrape_job import ScrapeJob
from app.services.scrape_jobs_service import mark_done


def test_mark_done_accepts_raw_datetime_in_payload(db):
    """Regression test: a backoff-skip result carries a raw next_allowed_at
    datetime in its payload. Before the fix, committing this raised
    StatementError('Object of type datetime is not JSON serializable') and
    every legitimate backoff skip was misreported as job_failed.
    """
    job = ScrapeJob(
        source="olx",
        queue="browser",
        run_at=datetime.now(timezone.utc),
        status="running",
        priority=0,
    )
    db.add(job)
    db.commit()

    next_allowed_at = datetime.now(timezone.utc)
    mark_done(
        job,
        result_status="skipped",
        payload={"ok": True, "status": "skipped", "reason": "backoff", "next_allowed_at": next_allowed_at},
        duration_ms=123,
    )
    db.commit()  # must not raise

    db.refresh(job)
    assert job.status == "done"
    assert job.result_payload["reason"] == "backoff"
    assert job.result_payload["next_allowed_at"] == next_allowed_at.isoformat()
