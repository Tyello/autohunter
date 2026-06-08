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
    monkeypatch.setattr("app.services.operational_alerts_service.settings.filesystem_cleanup_cache_max_bytes", 100)
    monkeypatch.setattr("app.services.operational_alerts_service.settings.ram_alert_threshold", 85.0)
    monkeypatch.setattr("app.services.operational_alerts_service.settings.disk_alert_root_used_pct", 85.0)
    monkeypatch.setattr("app.services.operational_alerts_service.settings.resource_alert_throttle_seconds", 1800)

    a1 = collect_operational_alerts(db, now=now)
    keys1 = {a.key for a in a1}
    assert "ram_pressure" in keys1
    assert "disk_root_pressure" in keys1
    assert "disk_cache_pressure" in keys1
    cache_alert = next(a for a in a1 if a.key == "disk_cache_pressure")
    assert "Top 5 dirs:" in cache_alert.message
    assert "app.ops.cleanup_filesystem" in cache_alert.message

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


def _add_mercadolivre_config(db, *, canary_enabled=False, browser_fallback_enabled=True):
    db.add(
        SourceConfig(
            source="mercadolivre",
            is_enabled=True,
            sched_minutes=30,
            browser_fallback_enabled=browser_fallback_enabled,
            extra={"impl": "v1", "mercadolivre_v2_canary_enabled": canary_enabled},
        )
    )


def test_source_stale_with_active_backoff_emits_single_consolidated_backoff_alert(db, monkeypatch):
    now = datetime.now(timezone.utc)
    monkeypatch.setattr("app.services.operational_alerts_service.settings.enable_playwright", True)
    db.add(SystemLog(component="scheduler", message="heartbeat", created_at=now - timedelta(minutes=1)))
    _add_mercadolivre_config(db, canary_enabled=False)
    db.add(
        SourceState(
            source="mercadolivre",
            last_effective_run_at=now - timedelta(minutes=182),
            last_status="skipped:backoff",
            next_allowed_at=now + timedelta(hours=2),
        )
    )
    db.commit()

    alerts = collect_operational_alerts(db, now=now, consume_cooldown=False)
    ml_alerts = [a for a in alerts if "mercadolivre" in a.key]
    keys = {a.key for a in ml_alerts}

    assert [a.key for a in ml_alerts] == ["source_blocked_backoff:mercadolivre"]
    assert "source_stale:mercadolivre" not in keys
    assert "source_backoff:mercadolivre" not in keys
    alert = ml_alerts[0]
    assert "Source mercadolivre em backoff ativo até" in alert.message
    assert "Sem execução real há 182m porque o circuit breaker/backoff está segurando novas tentativas." in alert.message
    assert "/admin sources show mercadolivre" in alert.message
    assert "/admin sources mercadolivre" not in alert.message
    assert "/admin sources canary mercadolivre report" not in alert.message


def test_source_active_long_backoff_without_stale_emits_backoff_alert(db):
    now = datetime.now(timezone.utc)
    db.add(SystemLog(component="scheduler", message="heartbeat", created_at=now - timedelta(minutes=1)))
    _add_mercadolivre_config(db, canary_enabled=False)
    db.add(
        SourceState(
            source="mercadolivre",
            last_effective_run_at=now - timedelta(minutes=20),
            last_status="blocked",
            next_allowed_at=now + timedelta(hours=2),
        )
    )
    db.commit()

    alerts = collect_operational_alerts(db, now=now, consume_cooldown=False)
    ml_alerts = [a for a in alerts if "mercadolivre" in a.key]

    assert [a.key for a in ml_alerts] == ["source_blocked_backoff:mercadolivre"]
    assert "em backoff ativo até" in ml_alerts[0].message
    assert "Sem execução real" not in ml_alerts[0].message


def test_source_stale_without_backoff_emits_stale_alert(db):
    now = datetime.now(timezone.utc)
    db.add(SystemLog(component="scheduler", message="heartbeat", created_at=now - timedelta(minutes=1)))
    _add_mercadolivre_config(db, canary_enabled=False)
    db.add(
        SourceState(
            source="mercadolivre",
            last_effective_run_at=now - timedelta(hours=6),
            last_status="error",
        )
    )
    db.commit()

    keys = {a.key for a in collect_operational_alerts(db, now=now, consume_cooldown=False)}

    assert "source_stale:mercadolivre" in keys
    assert "source_blocked_backoff:mercadolivre" not in keys


def test_mercadolivre_canary_disabled_does_not_include_canary_report(db, monkeypatch):
    now = datetime.now(timezone.utc)
    monkeypatch.setattr("app.services.operational_alerts_service.settings.enable_playwright", True)
    db.add(SystemLog(component="scheduler", message="heartbeat", created_at=now - timedelta(minutes=1)))
    _add_mercadolivre_config(db, canary_enabled=False)
    db.add(
        SourceState(
            source="mercadolivre",
            last_effective_run_at=now - timedelta(minutes=181),
            last_status="skipped:backoff",
            next_allowed_at=now + timedelta(hours=2),
        )
    )
    db.commit()

    alert = next(a for a in collect_operational_alerts(db, now=now, consume_cooldown=False) if a.key == "source_blocked_backoff:mercadolivre")

    assert "/admin sources canary mercadolivre report" not in alert.message
    assert "/admin sources show mercadolivre" in alert.message


def test_mercadolivre_canary_effective_includes_canary_report(db, monkeypatch):
    now = datetime.now(timezone.utc)
    monkeypatch.setattr("app.services.operational_alerts_service.settings.enable_playwright", True)
    db.add(SystemLog(component="scheduler", message="heartbeat", created_at=now - timedelta(minutes=1)))
    _add_mercadolivre_config(db, canary_enabled=True, browser_fallback_enabled=True)
    db.add(
        SourceState(
            source="mercadolivre",
            last_effective_run_at=now - timedelta(minutes=181),
            last_status="skipped:backoff",
            next_allowed_at=now + timedelta(hours=2),
        )
    )
    db.commit()

    alert = next(a for a in collect_operational_alerts(db, now=now, consume_cooldown=False) if a.key == "source_blocked_backoff:mercadolivre")

    assert "/admin sources canary mercadolivre report" in alert.message
    assert "/admin sources show mercadolivre" in alert.message
    assert "/admin sources mercadolivre" not in alert.message


def test_backoff_correlation_suppresses_redundant_stale_backoff_blocked_alerts(db, monkeypatch):
    now = datetime.now(timezone.utc)
    monkeypatch.setattr("app.services.operational_alerts_service.settings.enable_playwright", True)
    db.add(SystemLog(component="scheduler", message="heartbeat", created_at=now - timedelta(minutes=1)))
    _add_mercadolivre_config(db, canary_enabled=True)
    db.add(
        SourceState(
            source="mercadolivre",
            last_effective_run_at=now - timedelta(hours=4),
            last_status="skipped:backoff",
            next_allowed_at=now + timedelta(hours=2),
        )
    )
    for i in range(3):
        db.add(SourceRun(source="mercadolivre", kind="scheduler", status="blocked", created_at=now - timedelta(minutes=i + 1)))
    db.commit()

    alerts = collect_operational_alerts(db, now=now, consume_cooldown=False)
    ml_keys = [a.key for a in alerts if "mercadolivre" in a.key]
    assert ml_keys == ["source_blocked_backoff:mercadolivre"]


def test_impl_drift_alert_for_enabled_source_with_runtime(db):
    now = datetime.now(timezone.utc)
    db.add(SystemLog(component="scheduler", message="heartbeat", created_at=now - timedelta(minutes=1)))
    db.add(
        SourceConfig(
            source="olx",
            is_enabled=True,
            sched_minutes=60,
            cooldown_minutes=0,
            rate_limit_seconds=0,
            extra={"impl": "v2"},
        )
    )
    db.add(
        SourceState(
            source="olx",
            last_run_at=now - timedelta(minutes=5),
            last_effective_run_at=now - timedelta(minutes=5),
            last_status="success",
            last_payload={"runtime_impl": "v1"},
        )
    )
    db.commit()

    alerts = collect_operational_alerts(db, now=now, consume_cooldown=False)
    alert = next(a for a in alerts if a.key == "source_impl_drift:olx")

    assert "Source olx impl drift" in alert.message
    assert "configured_impl=v2" in alert.message
    assert "expected_runtime_impl=v2" in alert.message
    assert "last_runtime_impl=v1" in alert.message
    assert "/admin sources show olx" in alert.message
    assert "/admin runall olx" in alert.message
    assert "/admin sources rollback mercadolivre v1" not in alert.message
    assert "revisar configuração V1/V2" in alert.message


def test_impl_drift_alert_not_emitted_when_alignment_ok(db):
    now = datetime.now(timezone.utc)
    db.add(SystemLog(component="scheduler", message="heartbeat", created_at=now - timedelta(minutes=1)))
    db.add(SourceConfig(source="olx", is_enabled=True, sched_minutes=60, cooldown_minutes=0, rate_limit_seconds=0, extra={"impl": "v2"}))
    db.add(
        SourceState(
            source="olx",
            last_run_at=now - timedelta(minutes=5),
            last_effective_run_at=now - timedelta(minutes=5),
            last_status="success",
            last_payload={"runtime_impl": "v2"},
        )
    )
    db.commit()

    keys = {a.key for a in collect_operational_alerts(db, now=now, consume_cooldown=False)}

    assert "source_impl_drift:olx" not in keys


def test_impl_drift_alert_not_emitted_when_alignment_unknown(db):
    now = datetime.now(timezone.utc)
    db.add(SystemLog(component="scheduler", message="heartbeat", created_at=now - timedelta(minutes=1)))
    db.add(SourceConfig(source="olx", is_enabled=True, sched_minutes=60, cooldown_minutes=0, rate_limit_seconds=0, extra={"impl": "v2"}))
    db.add(
        SourceState(
            source="olx",
            last_run_at=now - timedelta(minutes=5),
            last_effective_run_at=now - timedelta(minutes=5),
            last_status="success",
            last_payload={},
        )
    )
    db.commit()

    keys = {a.key for a in collect_operational_alerts(db, now=now, consume_cooldown=False)}

    assert "source_impl_drift:olx" not in keys


def test_impl_drift_alert_for_mercadolivre_mentions_rollback(db):
    now = datetime.now(timezone.utc)
    db.add(SystemLog(component="scheduler", message="heartbeat", created_at=now - timedelta(minutes=1)))
    db.add(
        SourceConfig(
            source="mercadolivre",
            is_enabled=True,
            sched_minutes=60,
            cooldown_minutes=0,
            rate_limit_seconds=0,
            extra={"impl": "v2"},
        )
    )
    db.add(
        SourceState(
            source="mercadolivre",
            last_run_at=now - timedelta(minutes=5),
            last_effective_run_at=now - timedelta(minutes=5),
            last_status="success",
            last_payload={"runtime_impl": "v1"},
        )
    )
    db.commit()

    alert = next(a for a in collect_operational_alerts(db, now=now, consume_cooldown=False) if a.key == "source_impl_drift:mercadolivre")

    assert "/admin sources rollback mercadolivre v1" in alert.message
