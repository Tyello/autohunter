from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.core.settings import settings


@dataclass
class CleanupStats:
    scanned: int = 0
    deleted: int = 0
    skipped: int = 0

    def to_dict(self) -> dict:
        return {
            "scanned": int(self.scanned),
            "deleted": int(self.deleted),
            "skipped": int(self.skipped),
        }


def _iter_files(base_dir: Path):
    if not base_dir.exists() or not base_dir.is_dir():
        return
    for p in base_dir.rglob("*"):
        if p.is_file():
            yield p


def _cleanup_dir(*, base_dir: Path, older_than_days: int, max_delete: int) -> CleanupStats:
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=max(0, int(older_than_days)))
    stats = CleanupStats()

    for path in _iter_files(base_dir) or []:
        stats.scanned += 1
        if stats.deleted >= max(0, int(max_delete)):
            stats.skipped += 1
            continue
        try:
            mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        except FileNotFoundError:
            continue
        if mtime > cutoff:
            continue
        try:
            path.unlink(missing_ok=True)
            stats.deleted += 1
        except Exception:
            stats.skipped += 1

    # cleanup empty dirs bottom-up
    if base_dir.exists() and base_dir.is_dir():
        for d in sorted([p for p in base_dir.rglob("*") if p.is_dir()], key=lambda x: len(x.parts), reverse=True):
            try:
                d.rmdir()
            except OSError:
                pass
    return stats


def run_filesystem_cleanup() -> dict:
    enabled = bool(getattr(settings, "filesystem_cleanup_enabled", True))
    artifacts_days = int(getattr(settings, "filesystem_cleanup_artifacts_days", 7) or 7)
    debug_days = int(getattr(settings, "filesystem_cleanup_debug_days", 7) or 7)
    max_delete = int(getattr(settings, "filesystem_cleanup_max_delete_per_run", 1000) or 1000)

    result = {
        "enabled": enabled,
        "artifacts_days": artifacts_days,
        "debug_days": debug_days,
        "max_delete": max_delete,
    }
    if not enabled:
        result["skipped"] = "disabled"
        return result

    artifacts_root = Path(settings.source_audit_root).expanduser().resolve()
    debug_root = Path(settings.runtime_cache_dir).expanduser().resolve() / "debug"

    artifacts = _cleanup_dir(base_dir=artifacts_root, older_than_days=artifacts_days, max_delete=max_delete)
    debug = _cleanup_dir(base_dir=debug_root, older_than_days=debug_days, max_delete=max_delete)

    result["artifacts"] = {"path": str(artifacts_root), **artifacts.to_dict()}
    result["debug"] = {"path": str(debug_root), **debug.to_dict()}
    result["deleted_total"] = artifacts.deleted + debug.deleted
    result["scanned_total"] = artifacts.scanned + debug.scanned
    result["skipped_total"] = artifacts.skipped + debug.skipped
    return result
