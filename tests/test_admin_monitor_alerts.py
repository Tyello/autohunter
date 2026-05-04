from datetime import datetime, timedelta, timezone

from app.models.system_log import SystemLog
from app.scheduler.admin_monitor_job import job_admin_monitor


def test_monitor_sends_to_admin(monkeypatch, db):
    now = datetime.now(timezone.utc)
    db.add(SystemLog(component="scheduler", message="heartbeat", created_at=now - timedelta(hours=4)))
    db.commit()
    sent = []
    monkeypatch.setattr("app.scheduler.admin_monitor_job.iter_admin_chat_ids", lambda: [10])
    monkeypatch.setattr("app.scheduler.admin_monitor_job.send_admin_text", lambda t: sent.append(t))
    job_admin_monitor()
    assert sent


def test_monitor_no_admin_chat(monkeypatch, db):
    now = datetime.now(timezone.utc)
    db.add(SystemLog(component="scheduler", message="heartbeat", created_at=now - timedelta(hours=4)))
    db.commit()
    monkeypatch.setattr("app.scheduler.admin_monitor_job.iter_admin_chat_ids", lambda: [])
    monkeypatch.setattr("app.scheduler.admin_monitor_job.send_admin_text", lambda _t: (_ for _ in ()).throw(AssertionError("should not send")))
    job_admin_monitor()


def test_monitor_no_admin_chat_without_alerts_no_warning_log(monkeypatch, db):
    now = datetime.now(timezone.utc)
    db.add(SystemLog(component="scheduler", message="heartbeat", created_at=now - timedelta(minutes=1)))
    db.commit()
    monkeypatch.setattr("app.scheduler.admin_monitor_job.iter_admin_chat_ids", lambda: [])
    job_admin_monitor()
    cnt = db.query(SystemLog).filter(SystemLog.component == "admin_monitor", SystemLog.message == "missing_admin_alert_chat").count()
    assert cnt == 0
