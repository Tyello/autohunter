from datetime import datetime, timezone, timedelta

from app.models.scrape_job import ScrapeJob
from app.models.source_run import SourceRun
from app.models.system_log import SystemLog
from app.services import autopilot_service
from app.models.autopilot_finding import AutopilotFinding


def test_autopilot_detects_stuck_queue(db, monkeypatch):
    now = datetime.now(timezone.utc)
    db.add(ScrapeJob(source="olx", queue="http", run_at=now - timedelta(hours=1), status="running", started_at=now - timedelta(minutes=40), locked_at=now - timedelta(minutes=40)))
    db.commit()
    monkeypatch.setattr(autopilot_service, "get_active_source_queue_partial_index_details", lambda _db: {"ok": True, "index_name": "uq_scrape_jobs_active_source_queue", "index_name_ok": True})
    cands = autopilot_service.build_candidates(db, now=now)
    assert any(c.kind == "scrape_jobs_stuck" for c in cands)


def test_autopilot_detects_heartbeat_without_runs(db, monkeypatch):
    now = datetime.now(timezone.utc)
    db.add(SystemLog(component="scheduler", message="heartbeat", created_at=now - timedelta(minutes=1)))
    db.commit()
    monkeypatch.setattr(autopilot_service, "get_active_source_queue_partial_index_details", lambda _db: {"ok": True, "index_name": "uq_scrape_jobs_active_source_queue", "index_name_ok": True})
    cands = autopilot_service.build_candidates(db, now=now)
    assert any(c.kind == "scheduler_heartbeat_without_runs" for c in cands)


def test_autopilot_heartbeat_with_recent_source_runs_does_not_alert(db, monkeypatch):
    now = datetime.now(timezone.utc)
    db.add(SystemLog(component="scheduler", message="heartbeat", created_at=now - timedelta(minutes=1)))
    db.add(SourceRun(source="vip_auctions", kind="scheduler", status="success", created_at=now - timedelta(minutes=2)))
    db.commit()
    monkeypatch.setattr(autopilot_service, "get_active_source_queue_partial_index_details", lambda _db: {"ok": True, "index_name": "uq_scrape_jobs_active_source_queue", "index_name_ok": True})
    cands = autopilot_service.build_candidates(db, now=now)
    assert not any(c.kind == "scheduler_heartbeat_without_runs" for c in cands)


def test_autopilot_heartbeat_source_run_error_counts_as_recent_run(db, monkeypatch):
    now = datetime.now(timezone.utc)
    db.add(SystemLog(component="scheduler", message="heartbeat", created_at=now - timedelta(minutes=1)))
    db.add(SourceRun(source="vip_auctions", kind="scheduler", status="error", created_at=now - timedelta(minutes=2), error="boom"))
    db.commit()
    monkeypatch.setattr(autopilot_service, "get_active_source_queue_partial_index_details", lambda _db: {"ok": True, "index_name": "uq_scrape_jobs_active_source_queue", "index_name_ok": True})
    cands = autopilot_service.build_candidates(db, now=now)
    assert not any(c.kind == "scheduler_heartbeat_without_runs" for c in cands)


def test_autopilot_consecutive_same_finding_respects_cooldown(db):
    now = datetime.now(timezone.utc)
    row = AutopilotFinding(
        status="open",
        kind="scheduler_heartbeat_without_runs",
        source=None,
        fingerprint="fp1",
        title="x",
        severity="error",
        first_seen_at=now,
        last_seen_at=now,
        hit_count=1,
        evidence={},
        suggested_actions="x",
    )
    db.add(row)
    db.commit()
    assert autopilot_service.should_alert(row, now=now)
    autopilot_service.mark_alerted(db, row, now=now)
    db.commit()
    assert not autopilot_service.should_alert(row, now=now + timedelta(seconds=10))


def test_autopilot_fingerprint_stable_and_digest_no_dupe(db, monkeypatch):
    now = datetime.now(timezone.utc)
    db.add(ScrapeJob(source="olx", queue="http", run_at=now - timedelta(hours=1), status="running", started_at=now - timedelta(minutes=40), locked_at=now - timedelta(minutes=40)))
    db.add(SourceRun(source="olx", kind="scheduler", status="error", created_at=now - timedelta(minutes=2), error="Timeout: x"))
    db.add(SourceRun(source="olx", kind="scheduler", status="error", created_at=now - timedelta(minutes=3), error="Timeout: x"))
    db.add(SourceRun(source="olx", kind="scheduler", status="error", created_at=now - timedelta(minutes=4), error="Timeout: x"))
    db.commit()
    monkeypatch.setattr(autopilot_service, "get_active_source_queue_partial_index_details", lambda _db: {"ok": True, "index_name": "uq_scrape_jobs_active_source_queue", "index_name_ok": True})

    cands = autopilot_service.build_candidates(db, now=now)
    stuck = [c for c in cands if c.kind == "scrape_jobs_stuck"][0]
    first = autopilot_service.upsert_findings(db, [stuck], now=now)
    second = autopilot_service.upsert_findings(db, [stuck], now=now + timedelta(minutes=1))
    db.commit()
    assert first[0].fingerprint == second[0].fingerprint
    assert second[0].hit_count == 2

    digest = autopilot_service.format_daily_digest([second[0]])
    assert "severity=" in digest


def test_autopilot_alerts_when_critical_scrape_jobs_index_missing(db, monkeypatch):
    now = datetime.now(timezone.utc)
    monkeypatch.setattr(autopilot_service, "get_active_source_queue_partial_index_details", lambda _db: {"ok": False, "reason": "not_found"})
    cands = autopilot_service.build_candidates(db, now=now)
    miss = [c for c in cands if c.kind == "scrape_jobs_missing_critical_index"]
    assert miss
    assert miss[0].evidence.get("reason") == "not_found"


def test_autopilot_no_alert_when_critical_scrape_jobs_index_exists(db, monkeypatch):
    now = datetime.now(timezone.utc)
    monkeypatch.setattr(
        autopilot_service,
        "get_active_source_queue_partial_index_details",
        lambda _db: {"ok": True, "index_name": "uq_scrape_jobs_active_source_queue", "index_name_ok": True},
    )
    cands = autopilot_service.build_candidates(db, now=now)
    assert not any(c.kind == "scrape_jobs_missing_critical_index" for c in cands)
