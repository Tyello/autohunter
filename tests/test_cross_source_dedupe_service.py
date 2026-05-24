from __future__ import annotations

from decimal import Decimal

from app.models.car_listing import CarListing
from app.repositories.car_listings_repo import _fallback_upsert_without_constraint
from app.services.cross_source_dedupe_service import (
    compute_cross_source_fingerprint,
    find_cross_source_fingerprint_collisions,
)


def _base_listing(**overrides):
    base = {
        "source": "olx",
        "external_id": "1",
        "title": "Honda Civic EX",
        "url": "https://olx/1",
        "make": "Honda",
        "model": "Civic",
        "year": 2019,
        "price": 80500,
        "mileage_km": 82000,
        "version": "EX",
        "transmission": "automatic",
    }
    base.update(overrides)
    return base


def test_compute_fingerprint_is_deterministic_cross_source():
    a = _base_listing(source="olx", external_id="olx-1")
    b = _base_listing(source="mercadolivre", external_id="ml-999")
    assert compute_cross_source_fingerprint(a) == compute_cross_source_fingerprint(b)


def test_source_external_id_url_do_not_affect_fingerprint():
    a = _base_listing(source="olx", external_id="1", url="https://olx/1")
    b = _base_listing(source="mercadolivre", external_id="abc", url="https://ml/xyz")
    assert compute_cross_source_fingerprint(a) == compute_cross_source_fingerprint(b)


def test_missing_minimum_signals_return_none():
    assert compute_cross_source_fingerprint({"make": "Honda", "model": "Civic", "price": 10}) is None
    assert compute_cross_source_fingerprint({"make": "Honda", "model": "Civic", "year": 2019}) is None


def test_price_bucket_behavior():
    a = _base_listing(price=80100)
    b = _base_listing(price=80999)
    c = _base_listing(price=82001)
    assert compute_cross_source_fingerprint(a) == compute_cross_source_fingerprint(b)
    assert compute_cross_source_fingerprint(a) != compute_cross_source_fingerprint(c)


def test_mileage_bucket_behavior():
    a = _base_listing(mileage_km=80001, price=None)
    b = _base_listing(mileage_km=84999, price=None)
    c = _base_listing(mileage_km=90000, price=None)
    assert compute_cross_source_fingerprint(a) == compute_cross_source_fingerprint(b)
    assert compute_cross_source_fingerprint(a) != compute_cross_source_fingerprint(c)


def test_repo_persists_cross_source_fingerprint_and_preserves_on_none_update(db):
    payload = _base_listing(price=90000, mileage_km=70000, external_id="persist-1")
    payload["cross_source_fingerprint"] = compute_cross_source_fingerprint(payload)
    _fallback_upsert_without_constraint(db, [payload], with_stats=False)
    row = db.query(CarListing).filter(CarListing.source == "olx", CarListing.external_id == "persist-1").first()
    assert row is not None
    assert row.cross_source_fingerprint is not None

    first_fp = row.cross_source_fingerprint
    update_payload = _base_listing(
        external_id="persist-1",
        price=None,
        mileage_km=None,
        make=None,
        model=None,
        year=None,
        doors=4,
        body_type="sedan",
    )
    _fallback_upsert_without_constraint(db, [update_payload], with_stats=False)
    row2 = db.query(CarListing).filter(CarListing.source == "olx", CarListing.external_id == "persist-1").first()
    assert row2.cross_source_fingerprint == first_fp
    assert row2.doors == 4
    assert row2.body_type == "sedan"


def test_find_cross_source_collisions_returns_only_multi_source(db):
    fp = compute_cross_source_fingerprint(_base_listing(source="olx", external_id="x1"))
    rows = [
        CarListing(source="olx", external_id="x1", title="a", url="https://olx/x1", price=Decimal("80000"), make="Honda", model="Civic", year=2019, mileage_km=80000, cross_source_fingerprint=fp),
        CarListing(source="mercadolivre", external_id="x2", title="b", url="https://ml/x2", price=Decimal("80500"), make="Honda", model="Civic", year=2019, mileage_km=81000, cross_source_fingerprint=fp),
        CarListing(source="olx", external_id="same-source", title="c", url="https://olx/c", price=Decimal("50000"), make="Fiat", model="Uno", year=2012, mileage_km=120000, cross_source_fingerprint="same-source-only"),
    ]
    db.add_all(rows)
    db.commit()

    out = find_cross_source_fingerprint_collisions(db, limit=10)
    assert any(item["fingerprint"] == fp for item in out)
    assert all(item["source_count"] > 1 for item in out)
    assert all(item["fingerprint"] != "same-source-only" for item in out)
