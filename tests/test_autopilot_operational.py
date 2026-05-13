from datetime import datetime, timezone, timedelta

from app.models.scrape_job import ScrapeJob
from app.models.source_run import SourceRun
from app.models.system_log import SystemLog
from app.services import autopilot_service


def test_autopilot_detects_stuck_queue(db, monkeypatch):
    now = datetime.now(timezone.utc)
    db.add(ScrapeJob(source="olx", queue="http", run_at=now - timedelta(hours=1), status="running", started_at=now - timedelta(minutes=40), locked_at=now - timedelta(minutes=40)))
    db.commit()
    monkeypatch.setattr(autopilot_service, "has_active_source_queue_partial_index", lambda _db: True)
    cands = autopilot_service.build_candidates(db, now=now)
    assert any(c.kind == "scrape_jobs_stuck" for c in cands)


def test_autopilot_detects_heartbeat_without_runs(db, monkeypatch):
    now = datetime.now(timezone.utc)
    db.add(SystemLog(component="scheduler", message="heartbeat", created_at=now - timedelta(minutes=1)))
    db.commit()
    monkeypatch.setattr(autopilot_service, "has_active_source_queue_partial_index", lambda _db: True)
    cands = autopilot_service.build_candidates(db, now=now)
    assert any(c.kind == "scheduler_heartbeat_without_runs" for c in cands)


def test_autopilot_fingerprint_stable_and_digest_no_dupe(db, monkeypatch):
    now = datetime.now(timezone.utc)
    db.add(ScrapeJob(source="olx", queue="http", run_at=now - timedelta(hours=1), status="running", started_at=now - timedelta(minutes=40), locked_at=now - timedelta(minutes=40)))
    db.add(SourceRun(source="olx", kind="scheduler", status="error", created_at=now - timedelta(minutes=2), error="Timeout: x"))
    db.add(SourceRun(source="olx", kind="scheduler", status="error", created_at=now - timedelta(minutes=3), error="Timeout: x"))
    db.add(SourceRun(source="olx", kind="scheduler", status="error", created_at=now - timedelta(minutes=4), error="Timeout: x"))
    db.commit()
    monkeypatch.setattr(autopilot_service, "has_active_source_queue_partial_index", lambda _db: True)

    cands = autopilot_service.build_candidates(db, now=now)
    stuck = [c for c in cands if c.kind == "scrape_jobs_stuck"][0]
    first = autopilot_service.upsert_findings(db, [stuck], now=now)
    second = autopilot_service.upsert_findings(db, [stuck], now=now + timedelta(minutes=1))
    db.commit()
    assert first[0].fingerprint == second[0].fingerprint
    assert second[0].hit_count == 2

    digest = autopilot_service.format_daily_digest([second[0]])
    assert "severity=" in digest
