from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.services import backup_health_service as svc


def test_backup_health_fail_when_dir_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(svc.settings, "backup_dir", str(tmp_path / "missing"))
    monkeypatch.setattr(svc.settings, "backup_max_age_hours", 30)
    out = svc.get_backup_health(now=datetime.now(timezone.utc))
    assert out.status == "FAIL"
    assert "diretório" in out.message


def test_backup_health_fail_when_dir_empty(monkeypatch, tmp_path):
    monkeypatch.setattr(svc.settings, "backup_dir", str(tmp_path))
    monkeypatch.setattr(svc.settings, "backup_max_age_hours", 30)
    out = svc.get_backup_health(now=datetime.now(timezone.utc))
    assert out.status == "FAIL"
    assert "nenhum backup" in out.message


def test_backup_health_ok_when_recent(monkeypatch, tmp_path):
    now = datetime(2026, 5, 25, 12, 0, tzinfo=timezone.utc)
    f = tmp_path / "autohunter_20260525_100000.sql.gz"
    f.write_bytes(b"x")
    ts = (now - timedelta(hours=2)).timestamp()
    f.touch()
    import os
    os.utime(f, (ts, ts))

    monkeypatch.setattr(svc.settings, "backup_dir", str(tmp_path))
    monkeypatch.setattr(svc.settings, "backup_max_age_hours", 30)
    out = svc.get_backup_health(now=now)
    assert out.status == "OK"
    assert out.latest_file == f.name
    assert out.latest_age_hours == 2


def test_backup_health_warning_when_old(monkeypatch, tmp_path):
    now = datetime(2026, 5, 25, 12, 0, tzinfo=timezone.utc)
    f = tmp_path / "autohunter_20260524_000000.sql.gz"
    f.write_bytes(b"x")
    ts = (now - timedelta(hours=40)).timestamp()
    import os
    os.utime(f, (ts, ts))

    monkeypatch.setattr(svc.settings, "backup_dir", str(tmp_path))
    monkeypatch.setattr(svc.settings, "backup_max_age_hours", 30)
    out = svc.get_backup_health(now=now)
    assert out.status == "WARNING"
    assert "limite 30h" in out.message


def test_backup_health_uses_most_recent(monkeypatch, tmp_path):
    now = datetime(2026, 5, 25, 12, 0, tzinfo=timezone.utc)
    old = tmp_path / "autohunter_older.sql.gz"
    new = tmp_path / "autohunter_newer.sql.gz"
    old.write_bytes(b"x")
    new.write_bytes(b"x")
    import os
    os.utime(old, ((now - timedelta(hours=20)).timestamp(), (now - timedelta(hours=20)).timestamp()))
    os.utime(new, ((now - timedelta(hours=1)).timestamp(), (now - timedelta(hours=1)).timestamp()))

    monkeypatch.setattr(svc.settings, "backup_dir", str(tmp_path))
    monkeypatch.setattr(svc.settings, "backup_max_age_hours", 30)
    out = svc.get_backup_health(now=now)
    assert out.latest_file == new.name


def test_backup_health_message_does_not_leak_database_url(monkeypatch, tmp_path):
    monkeypatch.setattr(svc.settings, "backup_dir", str(tmp_path))
    monkeypatch.setattr(svc.settings, "backup_max_age_hours", 30)
    out = svc.get_backup_health(now=datetime.now(timezone.utc))
    assert "postgres" not in out.message.lower()
    assert "database_url" not in out.message.lower()
