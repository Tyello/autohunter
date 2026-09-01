from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.services.source_staleness_service import (
    evaluate_source_staleness,
    heartbeat_is_stale,
    stale_threshold_minutes,
)


def test_stale_threshold_uses_factor_of_sched_minutes():
    assert stale_threshold_minutes(60, factor=2.0, min_global_minutes=180) == 180
    assert stale_threshold_minutes(120, factor=2.0, min_global_minutes=180) == 240


def test_stale_threshold_falls_back_to_default_when_sched_missing():
    assert stale_threshold_minutes(None, default_sched_minutes=60, factor=2.0, min_global_minutes=180) == 180


def test_evaluate_staleness_no_last_run_is_stale():
    now = datetime.now(timezone.utc)
    result = evaluate_source_staleness(now=now, last_run_at=None, sched_minutes=60)
    assert result.stale is True
    assert result.age_minutes is None
    assert result.overdue_minutes is None


def test_evaluate_staleness_recent_run_is_not_stale():
    now = datetime.now(timezone.utc)
    last_run = now - timedelta(minutes=5)
    result = evaluate_source_staleness(now=now, last_run_at=last_run, sched_minutes=60)
    assert result.stale is False
    assert result.age_minutes == 5
    assert result.overdue_minutes == 0


def test_evaluate_staleness_overdue_run_is_stale():
    now = datetime.now(timezone.utc)
    last_run = now - timedelta(minutes=300)
    result = evaluate_source_staleness(now=now, last_run_at=last_run, sched_minutes=60, min_global_minutes=180)
    assert result.stale is True
    assert result.threshold_minutes == 180
    assert result.overdue_minutes == 120


def test_evaluate_staleness_handles_naive_datetimes():
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    last_run = (datetime.now(timezone.utc) - timedelta(minutes=5)).replace(tzinfo=None)
    result = evaluate_source_staleness(now=now, last_run_at=last_run, sched_minutes=60)
    assert result.stale is False


def test_heartbeat_is_stale_when_missing():
    assert heartbeat_is_stale(datetime.now(timezone.utc), None) is True


def test_heartbeat_is_stale_when_older_than_cutoff():
    now = datetime.now(timezone.utc)
    last = now - timedelta(minutes=30)
    assert heartbeat_is_stale(now, last, stale_after_minutes=15) is True


def test_heartbeat_is_not_stale_when_recent():
    now = datetime.now(timezone.utc)
    last = now - timedelta(minutes=5)
    assert heartbeat_is_stale(now, last, stale_after_minutes=15) is False
