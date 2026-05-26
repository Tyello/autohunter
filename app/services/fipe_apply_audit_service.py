from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.db.session import SessionLocal
from app.services import system_logs_service


def _safe_skipped_counts(skipped_counts: Mapping[str, Any] | None) -> dict[str, int]:
    if not skipped_counts:
        return {}
    out: dict[str, int] = {}
    for key, value in skipped_counts.items():
        try:
            out[str(key)] = int(value)
        except Exception:
            continue
    return out


def log_fipe_apply_plan_run(
    *,
    reference_month: str,
    limit: int,
    dry_run: bool,
    planned_inserts_count: int,
    would_update_count: int,
    inserted_count: int,
    updated_count: int,
    skipped_counts: Mapping[str, Any] | None,
    sample_size: int,
    error: str | None = None,
) -> None:
    message = "fipe apply plan error" if error else ("fipe apply plan dry-run" if dry_run else "fipe apply plan live")
    payload = {
        "reference_month": str(reference_month),
        "limit": int(limit),
        "dry_run": bool(dry_run),
        "sample_size": int(sample_size),
        "planned_inserts_count": int(planned_inserts_count),
        "would_update_count": int(would_update_count),
        "inserted_count": int(inserted_count),
        "updated_count": int(updated_count),
        "skipped_counts": _safe_skipped_counts(skipped_counts),
        "error": str(error) if error else None,
    }

    try:
        with SessionLocal() as audit_db:
            system_logs_service.log(
                audit_db,
                level="error" if error else "info",
                component="fipe_apply_plan",
                message=message,
                payload=payload,
            )
            audit_db.commit()
    except Exception:
        return
