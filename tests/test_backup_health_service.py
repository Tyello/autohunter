from __future__ import annotations

import gzip
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.services import backup_health_service as svc


VALID_COUNTS = {
    "users": 1,
    "wishlists": 8,
    "wishlist_filters": 11,
    "accounts": 1,
    "account_members": 1,
    "source_configs": 16,
}


def _write_pg_dump(path: Path, counts: dict[str, int] | None = None, filler_bytes: int = 4096) -> None:
    counts = counts or VALID_COUNTS
    lines: list[str] = ["-- PostgreSQL database dump\n"]
    for table in svc.CRITICAL_TABLES:
        lines.append(f"COPY public.{table} (id) FROM stdin;\n")
        for idx in range(counts.get(table, 0)):
            lines.append(f"{table}-{idx}\n")
        lines.append("\\.\n")
    lines.append("-- filler " + ("x" * filler_bytes) + "\n")
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        fh.writelines(lines)


def _set_mtime(path: Path, ts: float) -> None:
    os.utime(path, (ts, ts))


def _configure_backup_settings(monkeypatch, tmp_path, *, max_age=30, min_size=1, validate=True):
    monkeypatch.setattr(svc.settings, "backup_dir", str(tmp_path))
    monkeypatch.setattr(svc.settings, "backup_max_age_hours", max_age)
    monkeypatch.setattr(svc.settings, "backup_min_size_bytes", min_size)
    monkeypatch.setattr(svc.settings, "backup_validate_critical_tables", validate)
    monkeypatch.setattr(svc.settings, "backup_min_users", 1)
    monkeypatch.setattr(svc.settings, "backup_min_wishlists", 1)
    monkeypatch.setattr(svc.settings, "backup_min_source_configs", 1)


def test_backup_health_fail_when_dir_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(svc.settings, "backup_dir", str(tmp_path / "missing"))
    monkeypatch.setattr(svc.settings, "backup_max_age_hours", 30)
    monkeypatch.setattr(svc.settings, "backup_min_size_bytes", 1)
    out = svc.get_backup_health(now=datetime.now(timezone.utc))
    assert out.status == "FAIL"
    assert "diretório" in out.message


def test_backup_health_fail_when_dir_empty(monkeypatch, tmp_path):
    _configure_backup_settings(monkeypatch, tmp_path)
    out = svc.get_backup_health(now=datetime.now(timezone.utc))
    assert out.status == "FAIL"
    assert "nenhum backup" in out.message


def test_backup_health_ok_when_recent_and_valid(monkeypatch, tmp_path):
    now = datetime(2026, 5, 25, 12, 0, tzinfo=timezone.utc)
    f = tmp_path / "autohunter_20260525_100000.sql.gz"
    _write_pg_dump(f)
    _set_mtime(f, (now - timedelta(hours=2)).timestamp())

    _configure_backup_settings(monkeypatch, tmp_path)
    out = svc.get_backup_health(now=now)
    assert out.status == "OK"
    assert out.latest_file == f.name
    assert out.latest_age_hours == 2
    assert out.latest_size_bytes == f.stat().st_size
    assert out.critical_counts["users"] == 1
    assert out.critical_counts["wishlists"] == 8
    assert out.critical_counts["source_configs"] == 16


def test_backup_health_fail_when_recent_but_too_small(monkeypatch, tmp_path):
    now = datetime(2026, 5, 25, 12, 0, tzinfo=timezone.utc)
    f = tmp_path / "autohunter_20260525_100000.sql.gz"
    _write_pg_dump(f)
    _set_mtime(f, (now - timedelta(hours=2)).timestamp())

    _configure_backup_settings(monkeypatch, tmp_path, min_size=f.stat().st_size + 1)
    out = svc.get_backup_health(now=now)
    assert out.status == "FAIL"
    assert "arquivo pequeno demais" in out.message


def test_backup_health_fail_when_recent_but_users_and_wishlists_zero(monkeypatch, tmp_path):
    now = datetime(2026, 5, 25, 12, 0, tzinfo=timezone.utc)
    f = tmp_path / "autohunter_20260525_100000.sql.gz"
    counts = dict(VALID_COUNTS)
    counts["users"] = 0
    counts["wishlists"] = 0
    _write_pg_dump(f, counts=counts)
    _set_mtime(f, (now - timedelta(hours=2)).timestamp())

    _configure_backup_settings(monkeypatch, tmp_path)
    out = svc.get_backup_health(now=now)
    assert out.status == "FAIL"
    assert out.critical_counts["users"] == 0
    assert out.critical_counts["wishlists"] == 0
    assert "users=0" in out.message
    assert "wishlists=0" in out.message


def test_backup_health_fail_when_source_configs_zero(monkeypatch, tmp_path):
    now = datetime(2026, 5, 25, 12, 0, tzinfo=timezone.utc)
    f = tmp_path / "autohunter_20260525_100000.sql.gz"
    counts = dict(VALID_COUNTS)
    counts["source_configs"] = 0
    _write_pg_dump(f, counts=counts)
    _set_mtime(f, (now - timedelta(hours=2)).timestamp())

    _configure_backup_settings(monkeypatch, tmp_path)
    out = svc.get_backup_health(now=now)
    assert out.status == "FAIL"
    assert out.critical_counts["source_configs"] == 0
    assert "source_configs=0" in out.message


def test_backup_health_warning_when_old_but_valid(monkeypatch, tmp_path):
    now = datetime(2026, 5, 25, 12, 0, tzinfo=timezone.utc)
    f = tmp_path / "autohunter_20260524_000000.sql.gz"
    _write_pg_dump(f)
    _set_mtime(f, (now - timedelta(hours=40)).timestamp())

    _configure_backup_settings(monkeypatch, tmp_path)
    out = svc.get_backup_health(now=now)
    assert out.status == "WARNING"
    assert "limite 30h" in out.message
    assert not out.validation_errors


def test_backup_health_uses_most_recent(monkeypatch, tmp_path):
    now = datetime(2026, 5, 25, 12, 0, tzinfo=timezone.utc)
    old = tmp_path / "autohunter_older.sql.gz"
    new = tmp_path / "autohunter_newer.sql.gz"
    _write_pg_dump(old)
    _write_pg_dump(new)
    _set_mtime(old, (now - timedelta(hours=20)).timestamp())
    _set_mtime(new, (now - timedelta(hours=1)).timestamp())

    _configure_backup_settings(monkeypatch, tmp_path)
    out = svc.get_backup_health(now=now)
    assert out.latest_file == new.name


def test_backup_health_message_does_not_leak_database_url(monkeypatch, tmp_path):
    _configure_backup_settings(monkeypatch, tmp_path)
    out = svc.get_backup_health(now=datetime.now(timezone.utc))
    assert "postgres" not in out.message.lower()
    assert "database_url" not in out.message.lower()


def test_backup_health_uses_default_dir_when_setting_empty(monkeypatch, tmp_path):
    now = datetime(2026, 5, 25, 12, 0, tzinfo=timezone.utc)
    fallback_dir = tmp_path / "fallback-backup-dir"
    fallback_dir.mkdir(parents=True, exist_ok=True)
    f = fallback_dir / "autohunter_20260525_100000.sql.gz"
    _write_pg_dump(f)
    _set_mtime(f, (now - timedelta(hours=1)).timestamp())

    monkeypatch.setattr(svc.settings, "backup_dir", "")
    monkeypatch.setattr(svc.settings, "backup_max_age_hours", 30)
    monkeypatch.setattr(svc.settings, "backup_min_size_bytes", 1)
    monkeypatch.setattr(svc.settings, "backup_validate_critical_tables", True)
    monkeypatch.setattr(svc, "DEFAULT_BACKUP_DIR", str(fallback_dir))

    out = svc.get_backup_health(now=now)
    assert out.status == "OK"
    assert out.backup_dir == str(fallback_dir)


def test_backup_health_uses_default_max_age_when_setting_invalid(monkeypatch, tmp_path):
    now = datetime(2026, 5, 25, 12, 0, tzinfo=timezone.utc)
    f = tmp_path / "autohunter_20260524_000000.sql.gz"
    _write_pg_dump(f)
    _set_mtime(f, (now - timedelta(hours=12)).timestamp())

    monkeypatch.setattr(svc.settings, "backup_dir", str(tmp_path))
    monkeypatch.setattr(svc.settings, "backup_max_age_hours", "invalid")
    monkeypatch.setattr(svc.settings, "backup_min_size_bytes", 1)
    monkeypatch.setattr(svc.settings, "backup_validate_critical_tables", True)
    monkeypatch.setattr(svc, "DEFAULT_BACKUP_MAX_AGE_HOURS", 30)

    out = svc.get_backup_health(now=now)
    assert out.status == "OK"
    assert out.max_age_hours == 30


def test_env_example_contains_autohunter_backup_vars():
    content = Path(".env.example").read_text(encoding="utf-8")
    assert "AUTOHUNTER_BACKUP_DIR=" in content
    assert "AUTOHUNTER_BACKUP_MAX_AGE_HOURS=" in content
    assert "AUTOHUNTER_BACKUP_MIN_SIZE_BYTES=" in content
    assert "AUTOHUNTER_BACKUP_VALIDATE_CRITICAL_TABLES=" in content
    assert "AUTOHUNTER_BACKUP_MIN_USERS=" in content
    assert "AUTOHUNTER_BACKUP_MIN_WISHLISTS=" in content
    assert "AUTOHUNTER_BACKUP_MIN_SOURCE_CONFIGS=" in content


def test_backup_health_settings_dir_used_when_configured(monkeypatch, tmp_path):
    now = datetime(2026, 5, 25, 12, 0, tzinfo=timezone.utc)
    f = tmp_path / "autohunter_20260525_100000.sql.gz"
    _write_pg_dump(f)
    _set_mtime(f, (now - timedelta(hours=1)).timestamp())

    _configure_backup_settings(monkeypatch, tmp_path)
    out = svc.get_backup_health(now=now)
    assert out.status == "OK"
    assert out.backup_dir == str(tmp_path)


def test_backup_health_uses_settings_max_age_when_valid(monkeypatch, tmp_path):
    now = datetime(2026, 5, 25, 12, 0, tzinfo=timezone.utc)
    f = tmp_path / "autohunter_20260525_000000.sql.gz"
    _write_pg_dump(f)
    _set_mtime(f, (now - timedelta(hours=12)).timestamp())

    _configure_backup_settings(monkeypatch, tmp_path, max_age=10)
    out = svc.get_backup_health(now=now)
    assert out.status == "WARNING"
    assert out.max_age_hours == 10
