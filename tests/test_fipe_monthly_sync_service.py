from decimal import Decimal

import pytest

from app.models.fipe_catalog_entry import FipeCatalogEntry
from app.services.fipe_monthly_sync_service import (
    finish_fipe_sync_run,
    normalize_fipe_month,
    normalize_fipe_text,
    start_fipe_sync_run,
    upsert_fipe_catalog_entries,
)


def test_normalization_month_and_text():
    assert normalize_fipe_month("2026-05") == "2026-05"
    with pytest.raises(ValueError):
        normalize_fipe_month("2026-13")
    assert normalize_fipe_text("  Honda   Civic ") == "Honda Civic"


def test_upsert_dry_run(db):
    out = upsert_fipe_catalog_entries(db, [{"model_name": "Civic", "price": "100000"}], reference_month="2026-05", dry_run=True)
    assert out["valid"] == 1
    assert db.query(FipeCatalogEntry).count() == 0


def test_upsert_insert_and_update(db):
    out1 = upsert_fipe_catalog_entries(db, [{"brand_code": "25", "model_code": "4828", "year_code": "2015-1", "model_name": "Civic", "price": "100000"}], reference_month="2026-05")
    assert out1["inserted"] == 1
    out2 = upsert_fipe_catalog_entries(db, [{"brand_code": "25", "model_code": "4828", "year_code": "2015-1", "model_name": "Civic LXR", "price": "120000"}], reference_month="2026-05")
    assert out2["updated"] == 1
    row = db.query(FipeCatalogEntry).first()
    assert row.price == Decimal("120000")
    assert row.model_name == "Civic LXR"


def test_validation_skips_invalid_and_month_error(db):
    out = upsert_fipe_catalog_entries(db, [{"model_name": "", "price": "100"}, {"model_name": "X", "price": 0}], reference_month="2026-05")
    assert out["skipped_invalid"] == 2
    with pytest.raises(ValueError):
        upsert_fipe_catalog_entries(db, [{"model_name": "X", "price": "100"}], reference_month="2026-99")


def test_sync_run_start_finish(db):
    run = start_fipe_sync_run(db, reference_month="2026-05", source="external_pipeline")
    assert run.status == "running"
    done = finish_fipe_sync_run(db, run.id, status="completed", counters={"total": 10, "inserted": 7, "updated": 3})
    assert done.status == "completed"
    assert done.rows_seen == 10
