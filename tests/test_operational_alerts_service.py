from datetime import datetime, timedelta, timezone

from app.models.source_config import SourceConfig
from app.models.source_state import SourceState
from app.models.system_log import SystemLog
from app.services.operational_alerts_service import collect_operational_alerts


def test_no_alert_when_healthy(db):
    now = datetime.now(timezone.utc)
    db.add(SystemLog(component="scheduler", message="heartbeat", created_at=now - timedelta(minutes=1)))
    db.commit()
    assert collect_operational_alerts(db, now=now) == []


def test_scheduler_stale_and_cooldown(db):
    now = datetime.now(timezone.utc)
    db.add(SystemLog(component="scheduler", message="heartbeat", created_at=now - timedelta(hours=4)))
    db.commit()
    a1 = collect_operational_alerts(db, now=now)
    assert any(a.key == "scheduler_stale_global" for a in a1)
    a2 = collect_operational_alerts(db, now=now + timedelta(minutes=5))
    assert not any(a.key == "scheduler_stale_global" for a in a2)
    a3 = collect_operational_alerts(db, now=now + timedelta(minutes=31))
    assert any(a.key == "scheduler_stale_global" for a in a3)


def test_primary_stale_alerts_but_experimental_not(db):
    now = datetime.now(timezone.utc)
    old = now - timedelta(hours=6)
    db.add(SourceConfig(source="olx", is_enabled=True, sched_minutes=30))
    db.add(SourceState(source="olx", last_effective_run_at=old, last_status="error"))
    db.add(SourceConfig(source="kavak", is_enabled=True, sched_minutes=30))
    db.add(SourceState(source="kavak", last_effective_run_at=old, last_status="error"))
    db.commit()
    keys = {a.key for a in collect_operational_alerts(db, now=now)}
    assert "source_stale:olx" in keys
    assert "source_stale:kavak" not in keys
