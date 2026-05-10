from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.services.filesystem_cleanup_service import _cleanup_dir


def _touch_with_age(path: Path, *, days_old: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("x", encoding="utf-8")
    ts = (datetime.now(timezone.utc) - timedelta(days=days_old)).timestamp()
    path.touch()
    import os
    os.utime(path, (ts, ts))


def test_cleanup_dir_removes_only_old_files(tmp_path):
    old_file = tmp_path / "old" / "old.txt"
    fresh_file = tmp_path / "new" / "new.txt"
    _touch_with_age(old_file, days_old=10)
    _touch_with_age(fresh_file, days_old=1)

    stats = _cleanup_dir(base_dir=tmp_path, older_than_days=7, max_delete=100)

    assert stats.deleted == 1
    assert not old_file.exists()
    assert fresh_file.exists()


def test_cleanup_dir_respects_max_delete(tmp_path):
    for i in range(5):
        _touch_with_age(tmp_path / f"f_{i}.txt", days_old=20)

    stats = _cleanup_dir(base_dir=tmp_path, older_than_days=7, max_delete=2)

    assert stats.deleted == 2
    remaining = list(tmp_path.rglob("*.txt"))
    assert len(remaining) == 3
