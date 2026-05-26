from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.services.filesystem_cleanup_service import _cleanup_dir, run_filesystem_cleanup


def _touch_with_age(path: Path, *, days_old: int, size: int = 1) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)
    ts = (datetime.now(timezone.utc) - timedelta(days=days_old)).timestamp()
    import os
    os.utime(path, (ts, ts))


def test_cleanup_dir_removes_only_old_files(tmp_path):
    old_file = tmp_path / "old" / "old.txt"
    fresh_file = tmp_path / "new" / "new.txt"
    _touch_with_age(old_file, days_old=10)
    _touch_with_age(fresh_file, days_old=1)

    stats = _cleanup_dir(base_dir=tmp_path, older_than_days=7, max_delete=100)

    assert stats.deleted == 1
    assert stats.candidates == 1
    assert not old_file.exists()
    assert fresh_file.exists()


def test_cleanup_dir_respects_max_delete(tmp_path):
    for i in range(5):
        _touch_with_age(tmp_path / f"f_{i}.txt", days_old=20)

    stats = _cleanup_dir(base_dir=tmp_path, older_than_days=7, max_delete=2)

    assert stats.deleted == 2
    remaining = list(tmp_path.rglob("*.txt"))
    assert len(remaining) == 3


def test_cleanup_dir_dry_run_does_not_delete(tmp_path):
    old_file = tmp_path / "old.txt"
    _touch_with_age(old_file, days_old=20, size=16)

    stats = _cleanup_dir(base_dir=tmp_path, older_than_days=7, max_delete=100, dry_run=True)

    assert stats.deleted == 1
    assert stats.bytes_freed == 16
    assert old_file.exists()


def test_run_filesystem_cleanup_safe_scope_only(monkeypatch, tmp_path):
    artifacts = tmp_path / "artifacts"
    cache = tmp_path / "cache"
    debug_old = cache / "debug" / "old.log"
    sensitive = cache / "pw-browsers" / "browser.bin"
    _touch_with_age(artifacts / "old_art.txt", days_old=10)
    _touch_with_age(debug_old, days_old=10)
    _touch_with_age(sensitive, days_old=30)

    monkeypatch.setattr("app.services.filesystem_cleanup_service.settings.filesystem_cleanup_enabled", True)
    monkeypatch.setattr("app.services.filesystem_cleanup_service.settings.filesystem_cleanup_artifacts_days", 7)
    monkeypatch.setattr("app.services.filesystem_cleanup_service.settings.filesystem_cleanup_debug_days", 7)
    monkeypatch.setattr("app.services.filesystem_cleanup_service.settings.filesystem_cleanup_max_delete_per_run", 100)
    monkeypatch.setattr("app.services.filesystem_cleanup_service.settings.source_audit_root", str(artifacts))
    monkeypatch.setattr("app.services.filesystem_cleanup_service.settings.runtime_cache_dir", str(cache))

    res = run_filesystem_cleanup(dry_run=False)
    assert res["deleted_total"] == 2
    assert not debug_old.exists()
    assert sensitive.exists()
