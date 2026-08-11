from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.core.settings import settings
from app.models.fipe_update_run import FipeUpdateRun
from app.services.fipe_monthly_pipeline_service import run_monthly_fipe_sync
from app.services.fipe_monthly_sync_service import normalize_fipe_month
from app.services.system_logs_service import log

LOCK_KEY = "monthly_fipe_update"


def _current_month() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


def should_run_monthly_fipe_update(db: Session, *, now: datetime | None = None) -> bool:
    now = now or datetime.now(timezone.utc)
    min_days = max(1, int(getattr(settings, "fipe_monthly_update_min_interval_days", 25) or 25))
    last_success = (
        db.query(FipeUpdateRun)
        .filter(FipeUpdateRun.lock_key == LOCK_KEY, FipeUpdateRun.status == "completed")
        .order_by(FipeUpdateRun.finished_at.desc().nullslast(), FipeUpdateRun.started_at.desc())
        .first()
    )
    if not last_success or not last_success.finished_at:
        return True
    finished_at = last_success.finished_at
    if finished_at.tzinfo is None:
        finished_at = finished_at.replace(tzinfo=timezone.utc)
    return finished_at <= now - timedelta(days=min_days)


def _has_running_lock(db: Session) -> bool:
    return bool(db.query(FipeUpdateRun.id).filter(FipeUpdateRun.lock_key == LOCK_KEY, FipeUpdateRun.status == "running").first())


def run_audited_monthly_fipe_update(db: Session, *, reference_month: str | None = None, input_path: str | Path | None = None, force: bool = False) -> FipeUpdateRun:
    month = normalize_fipe_month(reference_month or _current_month())
    path_value = str(input_path or getattr(settings, "fipe_monthly_update_input_path", "") or "").strip()
    started = datetime.now(timezone.utc)

    if _has_running_lock(db):
        run = FipeUpdateRun(started_at=started, status="skipped", reference_month=month, input_uri=path_value or None, lock_key=LOCK_KEY, error_message="execution lock already held")
        db.add(run); db.commit(); db.refresh(run)
        return run

    run = FipeUpdateRun(started_at=started, status="running", reference_month=month, input_uri=path_value or None, lock_key=LOCK_KEY)
    db.add(run); db.commit(); db.refresh(run)

    def finish(status: str, *, updated_rows: int = 0, error: str | None = None, payload: dict[str, Any] | None = None) -> FipeUpdateRun:
        finished = datetime.now(timezone.utc)
        run.status = status
        run.finished_at = finished
        run.duration_ms = int((finished - started).total_seconds() * 1000)
        run.updated_rows = int(updated_rows or 0)
        run.error_message = error
        run.payload = payload or None
        db.commit(); db.refresh(run)
        log(db, "info" if status in {"completed", "skipped"} else "error", "fipe_update", f"monthly FIPE update {status}", {"run_id": str(run.id), "reference_month": month, "updated_rows": run.updated_rows, "duration_ms": run.duration_ms, "error": error}, source="fipe", event_type=f"fipe_update_{status}")
        db.commit()
        db.refresh(run)
        return run

    if not bool(getattr(settings, "fipe_monthly_update_enabled", False)):
        return finish("skipped", error="kill switch disabled")
    if not force and not should_run_monthly_fipe_update(db, now=started):
        return finish("skipped", error="last successful update is still fresh")
    if not path_value:
        return finish("skipped", error="input path not configured")

    try:
        result = run_monthly_fipe_sync(db, reference_month=month, input_path=Path(path_value), apply=True)
        catalog = result.get("catalog_import") or {}
        price_plan = result.get("price_plan") or {}
        updated = int(catalog.get("inserted") or 0) + int(catalog.get("updated") or 0) + int(price_plan.get("inserted") or 0) + int(price_plan.get("updated") or 0)
        return finish("completed", updated_rows=updated, payload=result)
    except Exception as exc:
        db.rollback()
        return finish("failed", error=str(exc))


def get_fipe_update_status(db: Session) -> dict[str, Any]:
    last = db.query(FipeUpdateRun).order_by(FipeUpdateRun.started_at.desc()).first()
    day = max(1, min(28, int(getattr(settings, "fipe_monthly_update_day", 5) or 5)))
    hour = max(0, min(23, int(getattr(settings, "fipe_monthly_update_hour_utc", 5) or 5)))
    return {"last": last, "enabled": bool(getattr(settings, "fipe_monthly_update_enabled", False)), "next_schedule": f"monthly day {day:02d} at {hour:02d}:00 UTC", "due_by_last_success": should_run_monthly_fipe_update(db)}
