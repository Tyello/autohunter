from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.core.settings import settings


@dataclass
class CleanupStats:
    scanned: int = 0
    candidates: int = 0
    deleted: int = 0
    skipped: int = 0
    bytes_candidate: int = 0
    bytes_freed: int = 0

    def to_dict(self) -> dict:
        return {
            "scanned": int(self.scanned),
            "candidates": int(self.candidates),
            "deleted": int(self.deleted),
            "skipped": int(self.skipped),
            "bytes_candidate": int(self.bytes_candidate),
            "bytes_freed": int(self.bytes_freed),
        }


def _iter_files(base_dir: Path):
    if not base_dir.exists() or not base_dir.is_dir():
        return
    for p in base_dir.rglob("*"):
        if p.is_file() and not p.is_symlink():
            yield p


def _cleanup_dir(*, base_dir: Path, older_than_days: int, max_delete: int, dry_run: bool = False) -> CleanupStats:
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=max(0, int(older_than_days)))
    stats = CleanupStats()

    for path in _iter_files(base_dir) or []:
        stats.scanned += 1
        try:
            st = path.stat()
            mtime = datetime.fromtimestamp(st.st_mtime, tz=timezone.utc)
            size = int(st.st_size)
        except (FileNotFoundError, PermissionError, OSError):
            stats.skipped += 1
            continue

        if mtime > cutoff:
            continue

        stats.candidates += 1
        stats.bytes_candidate += size

        if stats.deleted >= max(0, int(max_delete)):
            stats.skipped += 1
            continue

        if dry_run:
            stats.deleted += 1
            stats.bytes_freed += size
            continue

        try:
            path.unlink(missing_ok=True)
            stats.deleted += 1
            stats.bytes_freed += size
        except Exception:
            stats.skipped += 1

    if not dry_run and base_dir.exists() and base_dir.is_dir():
        for d in sorted([p for p in base_dir.rglob("*") if p.is_dir()], key=lambda x: len(x.parts), reverse=True):
            try:
                d.rmdir()
            except OSError:
                pass
    return stats


def run_filesystem_cleanup(*, dry_run: bool = False) -> dict:
    enabled = bool(getattr(settings, "filesystem_cleanup_enabled", True))
    artifacts_days = int(getattr(settings, "filesystem_cleanup_artifacts_days", 7) or 7)
    debug_days = int(getattr(settings, "filesystem_cleanup_debug_days", 7) or 7)
    max_delete = int(getattr(settings, "filesystem_cleanup_max_delete_per_run", 1000) or 1000)

    result = {
        "enabled": enabled,
        "dry_run": bool(dry_run),
        "artifacts_days": artifacts_days,
        "debug_days": debug_days,
        "max_delete": max_delete,
    }
    if not enabled:
        result["skipped"] = "disabled"
        return result

    cache_root = Path(settings.runtime_cache_dir).expanduser().resolve()
    artifacts_root = Path(settings.source_audit_root).expanduser().resolve()
    debug_root = cache_root / "debug"
    temp_roots = [
        ("cache_tmp", cache_root / "tmp", int(getattr(settings, "filesystem_cleanup_cache_retention_days", artifacts_days) or artifacts_days)),
        ("cache_artifacts", cache_root / "artifacts", artifacts_days),
        ("artifacts", artifacts_root, artifacts_days),
        ("debug", debug_root, debug_days),
    ]
    # Avoid nested/overlapping roots (e.g. source_audit_root inside cache_artifacts).
    # Keep the parent root to guarantee each file is scanned/accounted only once.
    selected_roots: list[tuple[str, Path, int]] = []
    for label, root, retention_days in sorted(temp_roots, key=lambda item: len(item[1].parts)):
        resolved = root.resolve()
        overlap = False
        for _, parent, _ in selected_roots:
            try:
                resolved.relative_to(parent)
                overlap = True
                break
            except ValueError:
                pass
        if overlap:
            continue
        selected_roots.append((label, resolved, retention_days))

    parts: dict[str, dict] = {}
    for label, root, retention_days in selected_roots:
        stats = _cleanup_dir(base_dir=root, older_than_days=retention_days, max_delete=max_delete, dry_run=dry_run)
        parts[label] = {"path": str(root), "retention_days": int(retention_days), **stats.to_dict()}

    result.update(parts)
    result["deleted_total"] = sum(int(parts[k]["deleted"]) for k in parts)
    result["scanned_total"] = sum(int(parts[k]["scanned"]) for k in parts)
    result["candidates_total"] = sum(int(parts[k]["candidates"]) for k in parts)
    result["skipped_total"] = sum(int(parts[k]["skipped"]) for k in parts)
    result["bytes_candidate_total"] = sum(int(parts[k]["bytes_candidate"]) for k in parts)
    result["bytes_freed_total"] = sum(int(parts[k]["bytes_freed"]) for k in parts)
    if dry_run:
        result["would_delete_total"] = result["deleted_total"]
        result["would_free_total"] = result["bytes_freed_total"]
    return result
