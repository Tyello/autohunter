from __future__ import annotations

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.fipe_catalog_entry import FipeCatalogEntry
from app.models.fipe_price import FipePrice
from app.models.system_log import SystemLog
from app.services.fipe_monthly_sync_service import normalize_fipe_month


def _as_int(value) -> int:
    try:
        return int(value)
    except Exception:
        return 0


def _resolve_reference_month(db: Session, reference_month: str | None) -> str:
    if reference_month:
        return normalize_fipe_month(reference_month)

    month_price = db.query(func.max(FipePrice.reference_month)).scalar()
    month_catalog = db.query(func.max(FipeCatalogEntry.reference_month)).scalar()
    month = month_price or month_catalog
    if not month:
        raise ValueError("Sem dados FIPE em fipe_prices/fipe_catalog_entries para definir competência.")
    return str(month)


def build_fipe_apply_status_report(db: Session, *, reference_month: str | None = None, limit: int = 10) -> dict:
    month = _resolve_reference_month(db, reference_month)
    size = max(1, min(50, _as_int(limit) or 10))

    total_fipe_prices = (
        db.query(FipePrice)
        .filter(FipePrice.reference_month == month)
        .count()
    )

    rows = (
        db.query(SystemLog)
        .filter(SystemLog.component == "fipe_apply_plan")
        .order_by(SystemLog.created_at.desc())
        .limit(min(250, max(size * 10, size)))
        .all()
    )

    runs = []
    total_dry_runs = 0
    total_lives = 0
    total_inserted = 0
    total_errors = 0
    last_live = None
    last_dry_run = None

    for row in rows:
        payload = row.payload if isinstance(row.payload, dict) else {}
        if str(payload.get("reference_month") or "").strip() != month:
            continue
        message = str(row.message or "")
        low_msg = message.lower()
        is_error = "error" in low_msg
        dry_run = bool(payload.get("dry_run", True))
        if "live" in low_msg:
            dry_run = False

        run = {
            "created_at": row.created_at,
            "message": message,
            "dry_run": dry_run,
            "planned_inserts_count": _as_int(payload.get("planned_inserts_count")),
            "inserted_count": _as_int(payload.get("inserted_count")),
            "would_update_count": _as_int(payload.get("would_update_count")),
            "updated_count": _as_int(payload.get("updated_count")),
            "sample_size": _as_int(payload.get("sample_size")),
            "skipped_counts": payload.get("skipped_counts") if isinstance(payload.get("skipped_counts"), dict) else {},
            "error": str(payload.get("error") or payload.get("error_message") or "").strip() if is_error else "",
        }
        runs.append(run)

        if run["error"]:
            total_errors += 1
        if dry_run and not run["error"]:
            total_dry_runs += 1
            if last_dry_run is None:
                last_dry_run = run
        elif not run["error"]:
            total_lives += 1
            if last_live is None:
                last_live = run

        total_inserted += run["inserted_count"]

        if len(runs) >= size:
            break

    recommendation = f"rode /admin fipe apply_plan {month} dry 100"
    if total_errors > 0:
        recommendation = "verifique SystemLog e rode novamente com limite menor"
    elif any(r["dry_run"] and r["planned_inserts_count"] > 0 for r in runs) and total_lives == 0:
        recommendation = "valide e rode live com limite pequeno"
    elif total_lives > 0:
        recommendation = "rode /admin fipe coverage para validar cobertura"

    return {
        "reference_month": month,
        "fipe_prices_count": total_fipe_prices,
        "runs": runs,
        "aggregates": {
            "total_dry_runs": total_dry_runs,
            "total_lives": total_lives,
            "total_inserted": total_inserted,
            "total_errors": total_errors,
        },
        "last_live": last_live,
        "last_dry_run": last_dry_run,
        "recommendation": recommendation,
    }
