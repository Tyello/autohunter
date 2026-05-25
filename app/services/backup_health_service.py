from __future__ import annotations

from dataclasses import dataclass
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from app.core.settings import settings


BackupHealthStatus = Literal["OK", "WARNING", "FAIL"]


@dataclass(frozen=True)
class BackupHealthResult:
    status: BackupHealthStatus
    latest_file: str | None
    latest_age_hours: int | None
    backup_dir: str
    max_age_hours: int
    message: str


def _resolve_backup_dir() -> str:
    configured = getattr(settings, "backup_dir", None)
    if configured and str(configured).strip():
        return str(configured).strip()
    return (os.getenv("AUTOHUNTER_BACKUP_DIR") or "/var/backups/autohunter").strip()


def _resolve_max_age_hours() -> int:
    configured = getattr(settings, "backup_max_age_hours", None)
    if configured is not None:
        try:
            return int(configured)
        except (TypeError, ValueError):
            pass
    raw = os.getenv("AUTOHUNTER_BACKUP_MAX_AGE_HOURS")
    if raw is not None:
        try:
            return int(raw)
        except ValueError:
            pass
    return 30


def get_backup_health(now: datetime | None = None) -> BackupHealthResult:
    now_utc = now.astimezone(timezone.utc) if now else datetime.now(timezone.utc)
    backup_dir = _resolve_backup_dir()
    max_age_hours = _resolve_max_age_hours()
    base = Path(backup_dir)

    if not base.exists() or not base.is_dir():
        return BackupHealthResult("FAIL", None, None, backup_dir, max_age_hours, "diretório não encontrado")

    files = [p for p in base.glob("autohunter_*.sql.gz") if p.is_file()]
    if not files:
        return BackupHealthResult("FAIL", None, None, backup_dir, max_age_hours, "nenhum backup encontrado")

    latest = max(files, key=lambda p: p.stat().st_mtime)
    age_hours = int(max(0, (now_utc.timestamp() - latest.stat().st_mtime) // 3600))

    if age_hours <= max_age_hours:
        status: BackupHealthStatus = "OK"
        message = f"último há {age_hours}h"
    else:
        status = "WARNING"
        message = f"antigo — último há {age_hours}h, limite {max_age_hours}h"

    return BackupHealthResult(status, latest.name, age_hours, backup_dir, max_age_hours, message)
