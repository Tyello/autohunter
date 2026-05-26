import types
from datetime import datetime, timedelta, timezone

from app.models.source_run import SourceRun
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


def test_recurring_error_does_not_alert_for_experimental_or_deprioritized(db):
    now = datetime.now(timezone.utc)
    db.add(SystemLog(component="scheduler", message="heartbeat", created_at=now - timedelta(minutes=1)))
    db.add(SourceConfig(source="kavak", is_enabled=True, sched_minutes=30))
    db.add(SourceConfig(source="webmotors", is_enabled=True, sched_minutes=30))
    for _ in range(3):
        db.add(SourceRun(source="kavak", kind="scheduled", status="error", error="timeout", created_at=now - timedelta(minutes=10)))
        db.add(SourceRun(source="webmotors", kind="scheduled", status="error", error="timeout", created_at=now - timedelta(minutes=10)))
    db.commit()
    keys = {a.key for a in collect_operational_alerts(db, now=now)}
    assert "source_error:kavak:NET" not in keys
    assert "source_error:webmotors:NET" not in keys


def test_resource_alerts_ram_disk_cache_and_throttle(db, monkeypatch, tmp_path):
    now = datetime.now(timezone.utc)
    db.add(SystemLog(component="scheduler", message="heartbeat", created_at=now - timedelta(minutes=1)))
    db.commit()

    monkeypatch.setattr("app.services.operational_alerts_service.psutil.virtual_memory", lambda: types.SimpleNamespace(percent=95.0))
    monkeypatch.setattr("app.services.operational_alerts_service.shutil.disk_usage", lambda _p: types.SimpleNamespace(total=100, used=95, free=5))

    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    blob = cache_dir / "big.bin"
    blob.write_bytes(b"x" * 1024)

    monkeypatch.setattr("app.services.operational_alerts_service.settings.runtime_cache_dir", str(cache_dir))
    monkeypatch.setattr("app.services.operational_alerts_service.settings.disk_alert_cache_limit_gb", 0.0000001)
    monkeypatch.setattr("app.services.operational_alerts_service.settings.ram_alert_threshold", 85.0)
    monkeypatch.setattr("app.services.operational_alerts_service.settings.disk_alert_root_used_pct", 85.0)
    monkeypatch.setattr("app.services.operational_alerts_service.settings.resource_alert_throttle_seconds", 1800)

    a1 = collect_operational_alerts(db, now=now)
    keys1 = {a.key for a in a1}
    assert "ram_pressure" in keys1
    assert "disk_root_pressure" in keys1
    assert "disk_cache_pressure" in keys1
    cache_alert = next(a for a in a1 if a.key == "disk_cache_pressure")
    assert "Top dirs:" in cache_alert.message
    assert "disk_audit.py" in cache_alert.message
    assert "filesystem_cleanup.py --apply" in cache_alert.message

    a2 = collect_operational_alerts(db, now=now + timedelta(minutes=10))
    keys2 = {a.key for a in a2}
    assert "ram_pressure" not in keys2
    assert "disk_root_pressure" not in keys2
    assert "disk_cache_pressure" not in keys2

    a3 = collect_operational_alerts(db, now=now + timedelta(minutes=31))
    keys3 = {a.key for a in a3}
    assert "ram_pressure" in keys3
    assert "disk_root_pressure" in keys3
    assert "disk_cache_pressure" in keys3
