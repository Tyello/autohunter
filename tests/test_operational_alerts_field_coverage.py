from datetime import datetime, timedelta, timezone

from app.models.source_config import SourceConfig
from app.models.source_run import SourceRun
from app.models.system_log import SystemLog
from app.services.operational_alerts_service import collect_operational_alerts


def _add_success_run(db, *, source: str, created_at, items_found: int, year_present: int):
    db.add(
        SourceRun(
            source=source,
            kind="scheduled",
            status="success",
            items_found=items_found,
            created_at=created_at,
            payload={
                "field_coverage": {
                    "year": {"present": year_present, "rate": (year_present / items_found) if items_found else 0.0},
                }
            },
        )
    )


def test_alerts_when_critical_field_fill_rate_drops_below_threshold(db):
    now = datetime.now(timezone.utc)
    db.add(SystemLog(component="scheduler", message="heartbeat", created_at=now - timedelta(minutes=1)))
    db.add(SourceConfig(source="olx", is_enabled=True, sched_minutes=30))
    for i in range(5):
        _add_success_run(db, source="olx", created_at=now - timedelta(minutes=10 + i), items_found=10, year_present=0)
    db.commit()

    keys = {a.key for a in collect_operational_alerts(db, now=now)}
    assert "field_coverage:olx:year" in keys


def test_no_alert_when_fill_rate_healthy(db):
    now = datetime.now(timezone.utc)
    db.add(SystemLog(component="scheduler", message="heartbeat", created_at=now - timedelta(minutes=1)))
    db.add(SourceConfig(source="olx", is_enabled=True, sched_minutes=30))
    for i in range(5):
        _add_success_run(db, source="olx", created_at=now - timedelta(minutes=10 + i), items_found=10, year_present=9)
    db.commit()

    keys = {a.key for a in collect_operational_alerts(db, now=now)}
    assert "field_coverage:olx:year" not in keys


def test_no_alert_below_minimum_sample_size(db):
    now = datetime.now(timezone.utc)
    db.add(SystemLog(component="scheduler", message="heartbeat", created_at=now - timedelta(minutes=1)))
    db.add(SourceConfig(source="olx", is_enabled=True, sched_minutes=30))
    _add_success_run(db, source="olx", created_at=now - timedelta(minutes=5), items_found=5, year_present=0)
    db.commit()

    keys = {a.key for a in collect_operational_alerts(db, now=now)}
    assert "field_coverage:olx:year" not in keys


def test_field_coverage_alert_respects_cooldown(db):
    now = datetime.now(timezone.utc)
    db.add(SystemLog(component="scheduler", message="heartbeat", created_at=now - timedelta(minutes=1)))
    db.add(SourceConfig(source="olx", is_enabled=True, sched_minutes=30))
    for i in range(5):
        _add_success_run(db, source="olx", created_at=now - timedelta(minutes=10 + i), items_found=10, year_present=0)
    db.commit()

    a1 = collect_operational_alerts(db, now=now)
    assert any(a.key == "field_coverage:olx:year" for a in a1)
    a2 = collect_operational_alerts(db, now=now + timedelta(minutes=5))
    assert not any(a.key == "field_coverage:olx:year" for a in a2)
