from __future__ import annotations

import json
from decimal import Decimal
from uuid import uuid4

import pytest

from app.models.car_listing import CarListing
from app.models.fipe_catalog_entry import FipeCatalogEntry
from app.models.fipe_price import FipePrice
from app.models.fipe_sync_run import FipeSyncRun
from app.models.system_log import SystemLog
from app.services.fipe_monthly_pipeline_service import run_monthly_fipe_sync
from scripts.run_monthly_fipe_sync import main as monthly_sync_main


def _write_external_file(tmp_path, rows):
    path = tmp_path / "fipe_external.json"
    path.write_text(json.dumps(rows), encoding="utf-8")
    return path


def _external_civic_row(price="R$ 95.000,00"):
    return {
        "marca": "Honda",
        "modelo": "Civic",
        "ano": "2015 Gasolina",
        "combustivel": "Gasolina",
        "codigo_fipe": "001001-1",
        "valor": price,
        "tipo_veiculo": "car",
    }


def _listing(db, *, make="Honda", model="Civic", year=2015):
    row = CarListing(
        id=uuid4(),
        source="olx",
        external_id=str(uuid4()),
        url=f"https://example.test/{uuid4()}",
        make=make,
        model=model,
        year=year,
        price=Decimal("90000"),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def test_monthly_fipe_sync_dry_run_does_not_persist_catalog_or_prices(db, tmp_path):
    _listing(db)
    input_file = _write_external_file(tmp_path, [_external_civic_row()])

    result = run_monthly_fipe_sync(
        db,
        reference_month="2026-05",
        input_path=input_file,
        input_format="external-pipeline",
        apply=False,
    )

    assert result["ok"] is True
    assert result["mode"] == "dry-run"
    assert result["catalog_import"]["valid"] == 1
    assert result["catalog_import"]["inserted"] == 1
    assert result["catalog_import"]["dry_run"] is True
    assert result["warnings"] == [
        "dry-run sem catálogo FIPE persistido para o mês; "
        "resolver_coverage e price_plan não representam o apply final de fipe_prices"
    ]
    assert db.query(FipeCatalogEntry).count() == 0
    assert db.query(FipePrice).count() == 0
    assert db.query(FipeSyncRun).count() == 0
    log = db.query(SystemLog).filter(SystemLog.component == "fipe_monthly_sync").first()
    assert log is not None
    assert log.payload["mode"] == "dry-run"
    assert log.payload["warnings"] == result["warnings"]


def test_monthly_fipe_sync_apply_imports_catalog_and_applies_price_plan(db, tmp_path):
    _listing(db)
    input_file = _write_external_file(tmp_path, [_external_civic_row()])

    result = run_monthly_fipe_sync(
        db,
        reference_month="2026-05",
        input_path=input_file,
        input_format="external-pipeline",
        apply=True,
    )

    assert result["ok"] is True
    assert result["mode"] == "apply"
    assert result["catalog_import"]["inserted"] == 1
    assert result["resolver_coverage"]["status_counts"]["matched"] == 1
    assert result["price_plan"]["inserted_count"] == 1
    assert db.query(FipeCatalogEntry).count() == 1
    price = db.query(FipePrice).filter(FipePrice.reference_month == "2026-05").one()
    assert price.vehicle_key == "honda|civic|2015"
    assert int(price.fipe_price) == 95000
    run = db.query(FipeSyncRun).one()
    assert run.status == "completed"
    assert run.rows_inserted == 1


def test_monthly_fipe_sync_invalid_file_returns_error_and_logs(db, tmp_path):
    bad_file = tmp_path / "bad.json"
    bad_file.write_text("{not json", encoding="utf-8")

    with pytest.raises(Exception):
        run_monthly_fipe_sync(
            db,
            reference_month="2026-05",
            input_path=bad_file,
            input_format="external-pipeline",
            apply=False,
        )

    log = db.query(SystemLog).filter(SystemLog.component == "fipe_monthly_sync", SystemLog.level == "error").one()
    assert "error" in log.payload
    assert db.query(FipeCatalogEntry).count() == 0
    assert db.query(FipePrice).count() == 0


def test_monthly_fipe_sync_apply_is_idempotent_for_duplicate_month(db, tmp_path):
    _listing(db)
    input_file = _write_external_file(tmp_path, [_external_civic_row()])

    first = run_monthly_fipe_sync(db, reference_month="2026-05", input_path=input_file, apply=True)
    second = run_monthly_fipe_sync(db, reference_month="2026-05", input_path=input_file, apply=True)

    assert first["catalog_import"]["inserted"] == 1
    assert second["catalog_import"]["updated"] == 1
    assert first["price_plan"]["inserted_count"] == 1
    assert second["price_plan"]["inserted_count"] == 0
    assert second["price_plan"]["skipped_counts"]["already_exists"] >= 1
    assert db.query(FipeCatalogEntry).count() == 1
    assert db.query(FipePrice).count() == 1
    assert db.query(FipeSyncRun).count() == 2


def test_monthly_fipe_sync_absence_of_matches_does_not_apply_prices(db, tmp_path):
    _listing(db, make="Ford", model="Ka", year=2015)
    input_file = _write_external_file(tmp_path, [_external_civic_row()])

    result = run_monthly_fipe_sync(db, reference_month="2026-05", input_path=input_file, apply=True)

    assert result["catalog_import"]["inserted"] == 1
    assert result["resolver_coverage"]["status_counts"]["no_match"] == 1
    assert result["price_plan"]["planned_inserts_count"] == 0
    assert result["price_plan"]["inserted_count"] == 0
    assert db.query(FipePrice).count() == 0


def test_monthly_fipe_sync_cli_dry_run_command(db, tmp_path, capsys):
    input_file = _write_external_file(tmp_path, [_external_civic_row()])

    exit_code = monthly_sync_main([
        "--reference-month",
        "2026-05",
        "--input",
        str(input_file),
        "--format",
        "external-pipeline",
        "--dry-run",
    ])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "FIPE monthly sync concluído" in captured.out
    assert "modo: dry-run" in captured.out
    assert "catalog_import é simulação do arquivo novo" in captured.out
    assert "resolver_coverage e price_plan foram calculados somente sobre o catálogo já persistido" in captured.out
    assert "warning operacional: dry-run sem catálogo FIPE persistido para o mês" in captured.out
