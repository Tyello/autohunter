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
    out = upsert_fipe_catalog_entries(
        db,
        [{"brand_name": "Honda", "model_name": "Civic", "model_year": 2019, "price": "100000"}],
        reference_month="2026-05",
        dry_run=True,
    )
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
    out = upsert_fipe_catalog_entries(
        db,
        [{"model_name": "", "price": "100"}, {"model_name": "X", "price": 0}, {"model_name": "X", "price": "100"}],
        reference_month="2026-05",
    )
    assert out["skipped_invalid"] == 3
    with pytest.raises(ValueError):
        upsert_fipe_catalog_entries(db, [{"model_name": "X", "price": "100"}], reference_month="2026-99")


def test_text_identity_prevents_collapse(db):
    out = upsert_fipe_catalog_entries(
        db,
        [
            {"brand_name": "Honda", "model_name": "Civic", "price": "100000", "model_year": 2019},
            {"brand_name": "VW", "model_name": "Golf", "price": "120000", "model_year": 2019},
        ],
        reference_month="2026-05",
    )
    assert out["inserted"] == 2
    assert db.query(FipeCatalogEntry).count() == 2


def test_invalid_model_year_is_skipped_without_aborting(db):
    out = upsert_fipe_catalog_entries(
        db,
        [
            {"brand_name": "Honda", "model_name": "Civic", "model_year": "abc", "price": "100000"},
            {"brand_name": "VW", "model_name": "Golf", "model_year": 2018, "price": "120000"},
        ],
        reference_month="2026-05",
    )
    assert out["skipped_invalid"] == 1
    assert out["inserted"] == 1


def test_sync_run_start_finish(db):
    run = start_fipe_sync_run(db, reference_month="2026-05", source="external_pipeline")
    assert run.status == "running"
    done = finish_fipe_sync_run(db, run.id, status="completed", counters={"total": 10, "inserted": 7, "updated": 3})
    assert done.status == "completed"
    assert done.rows_seen == 10


def _make_rows(n):
    return [
        {"brand_name": "Honda", "model_name": f"Model{i}", "model_year": 2019, "price": "100000"}
        for i in range(n)
    ]


def test_upsert_batches_select_instead_of_per_row(db, monkeypatch):
    original_query = db.query
    call_count = {"n": 0}

    def counting_query(*args, **kwargs):
        if args and args[0] is FipeCatalogEntry:
            call_count["n"] += 1
        return original_query(*args, **kwargs)

    monkeypatch.setattr(db, "query", counting_query)

    upsert_fipe_catalog_entries(db, _make_rows(50), reference_month="2026-05", chunk_size=10)

    assert call_count["n"] == 5


def test_upsert_commits_per_chunk_not_once_or_per_row(db, monkeypatch):
    original_commit = db.commit
    commit_count = {"n": 0}

    def counting_commit():
        commit_count["n"] += 1
        return original_commit()

    monkeypatch.setattr(db, "commit", counting_commit)

    upsert_fipe_catalog_entries(db, _make_rows(50), reference_month="2026-05", chunk_size=10)

    assert commit_count["n"] == 5
    assert commit_count["n"] != 1
    assert commit_count["n"] != 50


def test_upsert_batched_result_matches_unbatched_baseline(db):
    from app.db.session import SessionLocal

    rows = _make_rows(23)

    db_big_chunk = SessionLocal()
    out_big = upsert_fipe_catalog_entries(db_big_chunk, rows, reference_month="2026-05", chunk_size=1000)
    entries_big = sorted(
        (e.model_name, str(e.price)) for e in db_big_chunk.query(FipeCatalogEntry).all()
    )
    db_big_chunk.query(FipeCatalogEntry).delete()
    db_big_chunk.commit()
    db_big_chunk.close()

    db_small_chunk = SessionLocal()
    out_small = upsert_fipe_catalog_entries(db_small_chunk, rows, reference_month="2026-05", chunk_size=5)
    entries_small = sorted(
        (e.model_name, str(e.price)) for e in db_small_chunk.query(FipeCatalogEntry).all()
    )
    db_small_chunk.close()

    assert out_big["inserted"] == out_small["inserted"]
    assert out_big["updated"] == out_small["updated"]
    assert out_big["skipped_invalid"] == out_small["skipped_invalid"]
    assert entries_big == entries_small
