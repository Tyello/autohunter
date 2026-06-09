from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.fipe_catalog_entry import FipeCatalogEntry
from app.models.fipe_price import FipePrice
from app.services import system_logs_service
from app.services.fipe_catalog_resolver_service import build_fipe_resolver_coverage_report
from app.services.fipe_external_pipeline_adapter import normalize_external_fipe_rows
from app.services.fipe_monthly_sync_service import (
    finish_fipe_sync_run,
    normalize_fipe_month,
    normalize_fipe_text,
    start_fipe_sync_run,
    upsert_fipe_catalog_entries,
)
from app.services.fipe_prices_planning_service import apply_fipe_price_plan, build_fipe_price_plan

SUPPORTED_FORMATS = {"external-pipeline"}


def load_monthly_fipe_input(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(f"arquivo não encontrado: {path}")
    if not path.is_file():
        raise ValueError(f"input não é um arquivo regular: {path}")

    suffix = path.suffix.lower()
    if suffix == ".json":
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, list):
            raise ValueError("JSON inválido: esperado list[dict]")
        if not all(isinstance(row, dict) for row in payload):
            raise ValueError("JSON inválido: todos os itens devem ser objetos")
        return payload

    if suffix == ".csv":
        with path.open("r", encoding="utf-8", newline="") as fh:
            reader = csv.DictReader(fh)
            if not reader.fieldnames:
                raise ValueError("CSV inválido: header ausente")
            return [dict(row) for row in reader]

    raise ValueError("formato de arquivo inválido: use .json ou .csv")


def build_fipe_catalog_report(
    db: Session, *, reference_month: str, source: str = "external_pipeline"
) -> dict[str, Any]:
    month = normalize_fipe_month(reference_month)
    source_norm = normalize_fipe_text(source) or "external_pipeline"
    base = db.query(FipeCatalogEntry).filter(
        FipeCatalogEntry.reference_month == month,
        FipeCatalogEntry.source == source_norm,
    )
    grouped_rows = (
        base.with_entities(FipeCatalogEntry.vehicle_type, func.count(FipeCatalogEntry.id))
        .group_by(FipeCatalogEntry.vehicle_type)
        .all()
    )
    by_type = {str(vehicle_type): int(count) for vehicle_type, count in grouped_rows}
    return {
        "reference_month": month,
        "source": source_norm,
        "catalog_entries_count": int(base.count()),
        "vehicle_type_counts": by_type,
    }


def _log_monthly_sync(
    db: Session, *, level: str, message: str, payload: dict[str, Any], event_type: str
) -> None:
    system_logs_service.log(
        db,
        level=level,
        component="fipe_monthly_sync",
        message=message,
        payload=payload,
        source="fipe",
        event_type=event_type,
    )
    db.commit()


def run_monthly_fipe_sync(
    db: Session,
    *,
    reference_month: str,
    input_path: Path,
    input_format: str = "external-pipeline",
    apply: bool = False,
    source: str = "external_pipeline",
    limit: int = 100,
    min_confidence: int = 80,
) -> dict[str, Any]:
    month = normalize_fipe_month(reference_month)
    source_norm = normalize_fipe_text(source) or "external_pipeline"
    if input_format not in SUPPORTED_FORMATS:
        raise ValueError(f"format inválido: {input_format}")

    mode = "apply" if apply else "dry-run"
    sync_run = None
    try:
        raw_rows = load_monthly_fipe_input(input_path)
        normalized_rows, adapter_counters = normalize_external_fipe_rows(
            raw_rows, reference_month=month
        )
        if adapter_counters["normalized"] == 0:
            raise ValueError("nenhuma linha normalizada pelo adapter externo")

        import_result = upsert_fipe_catalog_entries(
            db,
            normalized_rows,
            reference_month=month,
            source=source_norm,
            dry_run=not apply,
        )
        if import_result["valid"] == 0:
            raise ValueError("nenhuma linha válida para importar")

        if apply:
            sync_run = start_fipe_sync_run(db, reference_month=month, source=source_norm)
            finish_fipe_sync_run(db, sync_run.id, status="completed", counters=import_result)

        catalog_report = build_fipe_catalog_report(db, reference_month=month, source=source_norm)
        coverage_report = build_fipe_resolver_coverage_report(db, reference_month=month, limit=limit)
        if apply:
            price_plan_result = apply_fipe_price_plan(
                db,
                reference_month=month,
                limit=limit,
                min_confidence=min_confidence,
                dry_run=False,
                allow_updates=False,
            )
        else:
            price_plan_result = build_fipe_price_plan(
                db,
                reference_month=month,
                limit=limit,
                min_confidence=min_confidence,
            )

        fipe_prices_count = db.query(FipePrice).filter(FipePrice.reference_month == month).count()
        warnings = []
        if not apply and int(catalog_report.get("catalog_entries_count") or 0) == 0:
            warnings.append(
                "dry-run sem catálogo FIPE persistido para o mês; "
                "resolver_coverage e price_plan não representam o apply final de fipe_prices"
            )

        result = {
            "ok": True,
            "mode": mode,
            "reference_month": month,
            "input_path": str(input_path),
            "format": input_format,
            "source": source_norm,
            "adapter": adapter_counters,
            "catalog_import": import_result,
            "catalog_report": catalog_report,
            "resolver_coverage": coverage_report,
            "price_plan": price_plan_result,
            "fipe_prices_count": int(fipe_prices_count),
            "sync_run_id": str(sync_run.id) if sync_run is not None else None,
            "warnings": warnings,
        }
        _log_monthly_sync(
            db,
            level="info",
            message=f"monthly FIPE sync {mode} completed",
            payload=result,
            event_type="fipe_monthly_sync_completed",
        )
        return result
    except Exception as exc:
        if apply and sync_run is not None:
            try:
                finish_fipe_sync_run(db, sync_run.id, status="failed", error=str(exc))
            except Exception:
                db.rollback()
        error_payload = {
            "ok": False,
            "mode": mode,
            "reference_month": month,
            "input_path": str(input_path),
            "format": input_format,
            "source": source_norm,
            "error": str(exc),
        }
        try:
            _log_monthly_sync(
                db,
                level="error",
                message=f"monthly FIPE sync {mode} failed",
                payload=error_payload,
                event_type="fipe_monthly_sync_failed",
            )
        except Exception:
            db.rollback()
        raise
