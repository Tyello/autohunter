from datetime import datetime, timezone

from app.models.fipe_price import FipePrice
from app.models.system_log import SystemLog
from app.services.fipe_apply_status_service import build_fipe_apply_status_report


def _log(db, message: str, payload: dict | None = None):
    db.add(SystemLog(component="fipe_apply_plan", message=message, payload=payload or {}, created_at=datetime.now(timezone.utc)))
    db.commit()


def test_fipe_apply_status_no_logs_suggests_dry_run(db):
    db.add(FipePrice(vehicle_key="honda|civic|2015", fipe_price=100000, currency="BRL", reference_month="2026-05"))
    db.commit()
    report = build_fipe_apply_status_report(db, reference_month="2026-05", limit=10)
    assert report["aggregates"]["total_dry_runs"] == 0
    assert report["recommendation"] == "rode /admin fipe apply_plan 2026-05 dry 100"
    assert report["runs"] == []


def test_fipe_apply_status_counts_dry_live_error_and_prices(db):
    db.add(FipePrice(vehicle_key="a", fipe_price=1, currency="BRL", reference_month="2026-05"))
    db.add(FipePrice(vehicle_key="b", fipe_price=2, currency="BRL", reference_month="2026-05"))
    db.commit()

    _log(db, "fipe apply plan dry-run", {"reference_month": "2026-05", "dry_run": True, "planned_inserts_count": 20, "inserted_count": 0, "skipped_counts": {"no_match": 3}, "sample_size": 100})
    _log(db, "fipe apply plan live", {"reference_month": "2026-05", "dry_run": False, "planned_inserts_count": 20, "inserted_count": 20, "skipped_counts": {"already_exists": 2}, "sample_size": 100})
    _log(db, "fipe apply plan error", {"reference_month": "2026-05", "error": "boom", "dry_run": True})

    report = build_fipe_apply_status_report(db, reference_month="2026-05", limit=10)
    assert report["fipe_prices_count"] == 2
    assert report["aggregates"]["total_dry_runs"] == 1
    assert report["aggregates"]["total_lives"] == 1
    assert report["aggregates"]["total_inserted"] == 20
    assert report["aggregates"]["total_errors"] == 1
    assert report["last_live"] is not None
    assert report["last_dry_run"] is not None
    assert report["recommendation"] == "verifique SystemLog e rode novamente com limite menor"


def test_fipe_apply_status_limit_cap_50(db):
    db.add(FipePrice(vehicle_key="honda|civic|2015", fipe_price=100000, currency="BRL", reference_month="2026-05"))
    for _ in range(60):
        _log(db, "fipe apply plan dry-run", {"reference_month": "2026-05", "dry_run": True})
    report = build_fipe_apply_status_report(db, reference_month="2026-05", limit=999)
    assert len(report["runs"]) == 50


def test_fipe_apply_status_filters_logs_by_reference_month(db):
    db.add(FipePrice(vehicle_key="m1", fipe_price=1, currency="BRL", reference_month="2026-05"))
    db.add(FipePrice(vehicle_key="m2", fipe_price=2, currency="BRL", reference_month="2026-06"))
    db.commit()

    _log(db, "fipe apply plan dry-run", {"reference_month": "2026-05", "dry_run": True, "planned_inserts_count": 10, "inserted_count": 0})
    _log(db, "fipe apply plan live", {"reference_month": "2026-05", "dry_run": False, "planned_inserts_count": 5, "inserted_count": 5})
    _log(db, "fipe apply plan live", {"reference_month": "2026-06", "dry_run": False, "planned_inserts_count": 8, "inserted_count": 8})

    report = build_fipe_apply_status_report(db, reference_month="2026-05", limit=10)

    assert report["reference_month"] == "2026-05"
    assert report["fipe_prices_count"] == 1
    assert len(report["runs"]) == 2
    assert all((r.get("message") or "") in ("fipe apply plan dry-run", "fipe apply plan live") for r in report["runs"])
    assert report["aggregates"]["total_dry_runs"] == 1
    assert report["aggregates"]["total_lives"] == 1
    assert report["aggregates"]["total_inserted"] == 5


def test_fipe_apply_status_ignores_legacy_logs_without_reference_month(db):
    db.add(FipePrice(vehicle_key="x", fipe_price=1, currency="BRL", reference_month="2026-05"))
    db.commit()

    _log(db, "fipe apply plan dry-run", {"dry_run": True, "planned_inserts_count": 10})
    report = build_fipe_apply_status_report(db, reference_month="2026-05", limit=10)

    assert report["runs"] == []
    assert report["recommendation"] == "rode /admin fipe apply_plan 2026-05 dry 100"
