from __future__ import annotations

import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from sqlalchemy.orm import Session

from app.models.fipe_catalog_entry import FipeCatalogEntry
from app.models.fipe_sync_run import FipeSyncRun

_REF_MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def normalize_fipe_month(value: str | None) -> str:
    month = str(value or "").strip()
    if not _REF_MONTH_RE.match(month):
        raise ValueError("reference_month inválido; esperado YYYY-MM")
    return month


def normalize_fipe_text(value: str | None) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def start_fipe_sync_run(db: Session, *, reference_month: str, source: str) -> FipeSyncRun:
    run = FipeSyncRun(reference_month=normalize_fipe_month(reference_month), source=normalize_fipe_text(source) or "external_pipeline", status="running", started_at=datetime.now(timezone.utc))
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def finish_fipe_sync_run(db: Session, run_id, *, status, counters=None, error=None) -> FipeSyncRun:
    if status not in {"pending", "running", "completed", "failed"}:
        raise ValueError("status inválido")
    run = db.query(FipeSyncRun).filter(FipeSyncRun.id == run_id).first()
    if not run:
        raise ValueError("sync run não encontrada")
    counters = counters or {}
    run.status = status
    run.finished_at = datetime.now(timezone.utc)
    run.rows_seen = int(counters.get("total", run.rows_seen or 0))
    run.rows_inserted = int(counters.get("inserted", run.rows_inserted or 0))
    run.rows_updated = int(counters.get("updated", run.rows_updated or 0))
    run.error = normalize_fipe_text(error) or None
    db.commit()
    db.refresh(run)
    return run


def _parse_price(value) -> Decimal | None:
    try:
        price = Decimal(str(value).strip())
    except (InvalidOperation, ValueError, AttributeError):
        return None
    return price if price > 0 else None


def upsert_fipe_catalog_entries(db: Session, rows: list[dict], *, reference_month: str, source: str = "external_pipeline", dry_run: bool = False) -> dict:
    month = normalize_fipe_month(reference_month)
    source_norm = normalize_fipe_text(source) or "external_pipeline"
    counters = {"total": len(rows or []), "valid": 0, "inserted": 0, "updated": 0, "skipped_invalid": 0, "dry_run": bool(dry_run)}

    for row in rows or []:
        item = row or {}
        row_month = normalize_fipe_text(item.get("reference_month")) or month
        if not _REF_MONTH_RE.match(row_month):
            counters["skipped_invalid"] += 1
            continue
        model_name = normalize_fipe_text(item.get("model_name"))
        price = _parse_price(item.get("price"))
        if not model_name or price is None:
            counters["skipped_invalid"] += 1
            continue
        counters["valid"] += 1
        payload = {
            "reference_month": row_month,
            "vehicle_type": normalize_fipe_text(item.get("vehicle_type")) or "car",
            "brand_code": normalize_fipe_text(item.get("brand_code")) or None,
            "brand_name": normalize_fipe_text(item.get("brand_name")) or None,
            "model_code": normalize_fipe_text(item.get("model_code")) or None,
            "model_name": model_name,
            "year_code": normalize_fipe_text(item.get("year_code")) or None,
            "model_year": int(item.get("model_year")) if item.get("model_year") not in (None, "") else None,
            "fuel": normalize_fipe_text(item.get("fuel")) or None,
            "fipe_code": normalize_fipe_text(item.get("fipe_code")) or None,
            "price": price,
            "currency": (normalize_fipe_text(item.get("currency")) or "BRL").upper(),
            "raw_payload": item.get("raw_payload"),
            "source": source_norm,
        }
        existing = db.query(FipeCatalogEntry).filter(
            FipeCatalogEntry.reference_month == payload["reference_month"],
            FipeCatalogEntry.vehicle_type == payload["vehicle_type"],
            FipeCatalogEntry.brand_code == payload["brand_code"],
            FipeCatalogEntry.model_code == payload["model_code"],
            FipeCatalogEntry.year_code == payload["year_code"],
            FipeCatalogEntry.source == payload["source"],
        ).first()
        if existing:
            counters["updated"] += 1
            if not dry_run:
                for k, v in payload.items():
                    setattr(existing, k, v)
        else:
            counters["inserted"] += 1
            if not dry_run:
                db.add(FipeCatalogEntry(**payload))

    if not dry_run:
        db.commit()
    return counters
