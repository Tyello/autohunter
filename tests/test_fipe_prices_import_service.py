from decimal import Decimal

import pytest

from app.models.car_listing import CarListing
from app.models.fipe_price import FipePrice
from app.services.fipe_prices_import_service import (
    build_fipe_coverage_report,
    normalize_fipe_vehicle_key,
    upsert_fipe_prices,
)


def test_normalize_vehicle_key():
    assert normalize_fipe_vehicle_key("  HONDA   CIVIC  ") == "honda civic"


def test_upsert_insert(db):
    out = upsert_fipe_prices(db, [{"vehicle_key": "Honda|Civic|2015", "fipe_price": "100000"}], reference_month="2026-05")
    assert out["inserted"] == 1
    assert db.query(FipePrice).count() == 1


def test_upsert_update(db):
    upsert_fipe_prices(db, [{"vehicle_key": "honda|civic|2015", "fipe_price": "100000"}], reference_month="2026-05")
    out = upsert_fipe_prices(db, [{"vehicle_key": " honda|civic|2015 ", "fipe_price": "120000", "currency": "usd"}], reference_month="2026-05")
    row = db.query(FipePrice).first()
    assert out["updated"] == 1
    assert row.fipe_price == Decimal("120000")
    assert row.currency == "USD"


def test_upsert_dry_run(db):
    out = upsert_fipe_prices(db, [{"vehicle_key": "honda|civic|2015", "fipe_price": "100000"}], reference_month="2026-05", dry_run=True)
    assert out["inserted"] == 1
    assert out["dry_run"] is True
    assert db.query(FipePrice).count() == 0


def test_upsert_validation(db):
    out = upsert_fipe_prices(
        db,
        [
            {"vehicle_key": "", "fipe_price": "100"},
            {"vehicle_key": "x", "fipe_price": 0},
            {"vehicle_key": "x", "fipe_price": "abc"},
            {"vehicle_key": "x", "fipe_price": "100", "reference_month": "2026-13"},
        ],
        reference_month="2026-05",
    )
    assert out["valid"] == 0
    assert out["skipped_invalid"] == 4


@pytest.mark.parametrize("month", ["2026-99", "bad"])
def test_upsert_invalid_reference_month_raises(db, month):
    with pytest.raises(ValueError):
        upsert_fipe_prices(db, [], reference_month=month)


def test_coverage_report(db):
    db.add(CarListing(source="olx", external_id="1", url="u1", make="Honda", model="Civic", year=2015))
    db.add(CarListing(source="olx", external_id="2", url="u2", make="Volkswagen", model="Golf", year=2017))
    db.commit()
    upsert_fipe_prices(db, [{"vehicle_key": "honda|civic|2015", "fipe_price": "100000"}], reference_month="2026-05")

    report = build_fipe_coverage_report(db, reference_month="2026-05", limit=20)
    assert report["listings_with_fipe_keys"] == 2
    assert report["vehicle_keys_distinct"] >= 2
    assert report["vehicle_keys_covered"] == 1
    assert report["coverage_pct"] > 0
    assert "volkswagen|golf|2017" in report["examples_missing"]
