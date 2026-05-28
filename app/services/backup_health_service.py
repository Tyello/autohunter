from __future__ import annotations

import gzip
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from app.core.settings import settings


BackupHealthStatus = Literal["OK", "WARNING", "FAIL"]
DEFAULT_BACKUP_DIR = "/var/backups/autohunter"
DEFAULT_BACKUP_MAX_AGE_HOURS = 30
DEFAULT_BACKUP_MIN_SIZE_BYTES = 256 * 1024
DEFAULT_BACKUP_VALIDATE_CRITICAL_TABLES = True
DEFAULT_BACKUP_MIN_USERS = 1
DEFAULT_BACKUP_MIN_WISHLISTS = 1
DEFAULT_BACKUP_MIN_SOURCE_CONFIGS = 1
CRITICAL_TABLES: tuple[str, ...] = (
    "users",
    "wishlists",
    "wishlist_filters",
    "accounts",
    "account_members",
    "source_configs",
)
REQUIRED_NON_EMPTY_TABLES: tuple[tuple[str, str], ...] = (
    ("users", "backup_min_users"),
    ("wishlists", "backup_min_wishlists"),
    ("source_configs", "backup_min_source_configs"),
)


@dataclass(frozen=True)
class BackupHealthResult:
    status: BackupHealthStatus
    latest_file: str | None
    latest_age_hours: int | None
    backup_dir: str
    max_age_hours: int
    message: str
    latest_size_bytes: int | None = None
    min_size_bytes: int = DEFAULT_BACKUP_MIN_SIZE_BYTES
    critical_counts: dict[str, int | None] = field(default_factory=dict)
    validation_errors: tuple[str, ...] = ()
    validation_warnings: tuple[str, ...] = ()


def _resolve_backup_dir() -> str:
    configured = getattr(settings, "backup_dir", None)
    if configured and str(configured).strip():
        return str(configured).strip()
    return DEFAULT_BACKUP_DIR


def _resolve_int_setting(name: str, default: int) -> int:
    configured = getattr(settings, name, None)
    if configured is not None:
        try:
            value = int(configured)
            if value >= 0:
                return value
        except (TypeError, ValueError):
            pass
    return default


def _resolve_bool_setting(name: str, default: bool) -> bool:
    configured = getattr(settings, name, None)
    if configured is None:
        return default
    if isinstance(configured, bool):
        return configured
    normalized = str(configured).strip().lower()
    if normalized in {"1", "true", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "no", "n", "off"}:
        return False
    return default


def _resolve_max_age_hours() -> int:
    return _resolve_int_setting("backup_max_age_hours", DEFAULT_BACKUP_MAX_AGE_HOURS)


def _resolve_min_size_bytes() -> int:
    return _resolve_int_setting("backup_min_size_bytes", DEFAULT_BACKUP_MIN_SIZE_BYTES)


def _resolve_min_table_rows(table: str) -> int:
    defaults = {
        "users": DEFAULT_BACKUP_MIN_USERS,
        "wishlists": DEFAULT_BACKUP_MIN_WISHLISTS,
        "source_configs": DEFAULT_BACKUP_MIN_SOURCE_CONFIGS,
    }
    return _resolve_int_setting(f"backup_min_{table}", defaults.get(table, 0))


def _is_copy_start(line: str, table: str) -> bool:
    prefix = f"COPY public.{table}"
    return line.startswith(prefix) and " FROM stdin;" in line


def _estimate_copy_row_counts(path: Path, tables: tuple[str, ...]) -> tuple[dict[str, int | None], list[str]]:
    wanted = set(tables)
    counts: dict[str, int | None] = {table: None for table in tables}
    errors: list[str] = []
    current: str | None = None

    try:
        with gzip.open(path, "rt", encoding="utf-8", errors="replace") as fh:
            for raw_line in fh:
                line = raw_line.rstrip("\n")
                if current:
                    if line == r"\.":
                        current = None
                    else:
                        counts[current] = (counts[current] or 0) + 1
                    continue

                if not line.startswith("COPY public."):
                    continue
                for table in wanted:
                    if _is_copy_start(line, table):
                        counts[table] = 0
                        current = table
                        break
    except (OSError, EOFError, gzip.BadGzipFile) as exc:
        errors.append(f"não foi possível ler gzip/sql: {type(exc).__name__}")

    return counts, errors


def _validate_backup_file(latest: Path, min_size_bytes: int) -> tuple[dict[str, int | None], list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    size_bytes = latest.stat().st_size

    if min_size_bytes > 0 and size_bytes < min_size_bytes:
        errors.append(f"arquivo pequeno demais: {size_bytes} bytes < mínimo {min_size_bytes} bytes")

    if not _resolve_bool_setting("backup_validate_critical_tables", DEFAULT_BACKUP_VALIDATE_CRITICAL_TABLES):
        return {}, errors, warnings

    counts, read_errors = _estimate_copy_row_counts(latest, CRITICAL_TABLES)
    errors.extend(read_errors)

    for table in CRITICAL_TABLES:
        if counts.get(table) is None:
            errors.append(f"COPY public.{table} ausente")

    for table, _setting_name in REQUIRED_NON_EMPTY_TABLES:
        minimum = _resolve_min_table_rows(table)
        value = counts.get(table)
        if value is not None and value < minimum:
            errors.append(f"{table}={value} abaixo do mínimo {minimum}")

    empty_optional = [table for table in ("wishlist_filters", "accounts", "account_members") if counts.get(table) == 0]
    if empty_optional:
        warnings.append("tabelas críticas vazias: " + ", ".join(f"{t}=0" for t in empty_optional))

    return counts, errors, warnings


def get_backup_health(now: datetime | None = None) -> BackupHealthResult:
    now_utc = now.astimezone(timezone.utc) if now else datetime.now(timezone.utc)
    backup_dir = _resolve_backup_dir()
    max_age_hours = _resolve_max_age_hours()
    min_size_bytes = _resolve_min_size_bytes()
    base = Path(backup_dir)

    if not base.exists() or not base.is_dir():
        return BackupHealthResult(
            "FAIL",
            None,
            None,
            backup_dir,
            max_age_hours,
            "diretório não encontrado",
            min_size_bytes=min_size_bytes,
        )

    files = [p for p in base.glob("autohunter_*.sql.gz") if p.is_file()]
    if not files:
        return BackupHealthResult(
            "FAIL",
            None,
            None,
            backup_dir,
            max_age_hours,
            "nenhum backup encontrado",
            min_size_bytes=min_size_bytes,
        )

    latest = max(files, key=lambda p: p.stat().st_mtime)
    stat = latest.stat()
    age_hours = int(max(0, (now_utc.timestamp() - stat.st_mtime) // 3600))
    counts, validation_errors, validation_warnings = _validate_backup_file(latest, min_size_bytes)

    if validation_errors:
        status: BackupHealthStatus = "FAIL"
        message = "inválido — " + "; ".join(validation_errors[:4])
        if len(validation_errors) > 4:
            message += f"; +{len(validation_errors) - 4} motivo(s)"
    elif validation_warnings:
        status = "WARNING"
        if age_hours <= max_age_hours:
            message = f"atenção — último há {age_hours}h; " + "; ".join(validation_warnings)
        else:
            message = (
                f"antigo — último há {age_hours}h, limite {max_age_hours}h; "
                + "; ".join(validation_warnings)
            )
    elif age_hours <= max_age_hours:
        status = "OK"
        message = f"último há {age_hours}h"
    else:
        status = "WARNING"
        message = f"antigo — último há {age_hours}h, limite {max_age_hours}h"

    return BackupHealthResult(
        status,
        latest.name,
        age_hours,
        backup_dir,
        max_age_hours,
        message,
        latest_size_bytes=stat.st_size,
        min_size_bytes=min_size_bytes,
        critical_counts=counts,
        validation_errors=tuple(validation_errors),
        validation_warnings=tuple(validation_warnings),
    )
