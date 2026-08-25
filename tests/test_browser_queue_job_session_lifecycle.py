from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from app.core.settings import settings
from app.db.session import SessionLocal
from app.models.scrape_job import ScrapeJob
from app.models.system_log import SystemLog
from app.scheduler import browser_queue_job as bqj


def _make_job(db) -> int:
    job = ScrapeJob(
        source="olx",
        queue="browser",
        run_at=datetime.now(timezone.utc) - timedelta(seconds=1),
        priority=0,
        status="queued",
        attempt=0,
        max_attempts=3,
    )
    db.add(job)
    db.commit()
    return job.id


def _poison_session_then_raise(db, *_args, **_kwargs):
    """Simulates run_source_for_all_wishlists doing an internal commit that
    fails mid-transaction (e.g. a bad flush deep in the scrape pipeline),
    leaving the session in SQLAlchemy's "pending rollback" state without the
    caller ever getting a chance to rollback() before reuse.
    """
    db.execute(text("INSERT INTO this_table_does_not_exist (id) VALUES (1)"))
    db.commit()


@pytest.fixture(autouse=True)
def _enable_playwright(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "enable_playwright", True)


def test_internal_commit_failure_does_not_wedge_job_or_mask_status(monkeypatch: pytest.MonkeyPatch):
    """Root-cause regression test: an exception raised from inside
    run_source_for_all_wishlists after it already did partial internal work
    on the shared session must not cascade into repeated PendingRollbackError
    and must not leave the job stuck in status='running'.
    """
    setup_db = SessionLocal()
    job_id = _make_job(setup_db)
    setup_db.close()

    monkeypatch.setattr(bqj, "run_source_for_all_wishlists", _poison_session_then_raise)

    # Must not raise (old code would let PendingRollbackError escape uncaught).
    bqj.job_browser_queue_worker()

    check_db = SessionLocal()
    job = check_db.get(ScrapeJob, job_id)
    assert job is not None
    assert job.status == "queued"  # requeued for retry, not stuck "running"
    assert job.attempt == 1
    assert job.error and "this_table_does_not_exist" in job.error

    failure_logs = (
        check_db.query(SystemLog)
        .filter(SystemLog.component == "browser_queue_worker", SystemLog.event_type.is_(None))
        .filter(SystemLog.message == "job_failed")
        .all()
    )
    assert len(failure_logs) == 1
    check_db.close()


def test_worker_survives_multiple_consecutive_failing_runs(monkeypatch: pytest.MonkeyPatch):
    setup_db = SessionLocal()
    job_id = _make_job(setup_db)
    setup_db.close()

    monkeypatch.setattr(bqj, "run_source_for_all_wishlists", _poison_session_then_raise)

    for _ in range(3):
        db = SessionLocal()
        job = db.get(ScrapeJob, job_id)
        job.run_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        job.status = "queued"
        db.commit()
        db.close()

        bqj.job_browser_queue_worker()

    check_db = SessionLocal()
    job = check_db.get(ScrapeJob, job_id)
    assert job.status in ("queued", "failed")

    failure_logs = (
        check_db.query(SystemLog)
        .filter(SystemLog.component == "browser_queue_worker", SystemLog.message == "job_failed")
        .count()
    )
    assert failure_logs == 3
    check_db.close()


def test_success_path_logs_and_commits_job_independently_of_logging_failure(monkeypatch: pytest.MonkeyPatch):
    setup_db = SessionLocal()
    job_id = _make_job(setup_db)
    setup_db.close()

    def _fake_ok(db, *_args, **_kwargs):
        return {"status": "ok", "ok": True}

    monkeypatch.setattr(bqj, "run_source_for_all_wishlists", _fake_ok)

    def _boom_log(*_args, **_kwargs):
        raise RuntimeError("payload not json serializable")

    monkeypatch.setattr(bqj, "log", _boom_log)

    bqj.job_browser_queue_worker()

    check_db = SessionLocal()
    job = check_db.get(ScrapeJob, job_id)
    assert job.status == "done"
    assert job.result_status == "ok"
    check_db.close()
