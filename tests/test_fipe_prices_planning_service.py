from decimal import Decimal
from uuid import uuid4

from app.models.car_listing import CarListing
from app.models.fipe_price import FipePrice
from app.services.fipe_prices_planning_service import build_fipe_price_plan, build_fipe_price_plan_for_listing


def _listing(db, id_=None, make="Honda", model="Civic", year=2015):
    row = CarListing(id=id_ or uuid4(), source="olx", external_id=str(uuid4()), url=f"https://x/{uuid4()}", make=make, model=model, year=year)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def test_plan_for_listing_match_high_planned(db, monkeypatch):
    listing = _listing(db)
    monkeypatch.setattr("app.services.fipe_prices_planning_service.resolve_listing_to_fipe_candidates", lambda *a, **k: {
        "status": "matched",
        "best_candidate": {"confidence_label": "high", "confidence_score": 86, "price": 95000, "catalog_entry_id": "ce1", "fipe_code": "001", "model_name": "Civic"},
    })
    out = build_fipe_price_plan_for_listing(db, listing=listing, reference_month="2026-05")
    assert out["status"] == "planned"
    assert out["item"]["vehicle_key"] == "honda|civic|2015"


def test_plan_skips_reasons(db, monkeypatch):
    listing = _listing(db)
    for status in ("ambiguous", "no_match", "insufficient_data"):
        monkeypatch.setattr("app.services.fipe_prices_planning_service.resolve_listing_to_fipe_candidates", lambda *a, **k: {"status": status, "best_candidate": None})
        out = build_fipe_price_plan_for_listing(db, listing=listing, reference_month="2026-05")
        assert out["reason"] == status


def test_plan_below_confidence(db, monkeypatch):
    listing = _listing(db)
    monkeypatch.setattr("app.services.fipe_prices_planning_service.resolve_listing_to_fipe_candidates", lambda *a, **k: {
        "status": "matched", "best_candidate": {"confidence_label": "high", "confidence_score": 70, "price": 95000}
    })
    out = build_fipe_price_plan_for_listing(db, listing=listing, reference_month="2026-05", min_confidence=80)
    assert out["reason"] == "below_confidence"


def test_plan_missing_vehicle_key(db):
    listing = _listing(db, make=None)
    out = build_fipe_price_plan_for_listing(db, listing=listing, reference_month="2026-05")
    assert out["reason"] == "missing_vehicle_key"


def test_plan_already_exists_and_would_update(db, monkeypatch):
    listing = _listing(db)
    db.add(FipePrice(vehicle_key="honda|civic|2015", reference_month="2026-05", fipe_price=Decimal("90000"), currency="BRL"))
    db.commit()
    monkeypatch.setattr("app.services.fipe_prices_planning_service.resolve_listing_to_fipe_candidates", lambda *a, **k: {
        "status": "matched", "best_candidate": {"confidence_label": "high", "confidence_score": 90, "price": 95000}
    })
    out = build_fipe_price_plan_for_listing(db, listing=listing, reference_month="2026-05")
    assert out["reason"] == "already_exists"
    assert out["would_update"]["planned_fipe_price"] == 95000


def test_build_plan_no_persist(db, monkeypatch):
    l1 = _listing(db)
    l2 = _listing(db, make="VW", model="Golf", year=2017)

    def _resolver(_db, *, listing, reference_month, limit):
        if listing.id == l1.id:
            return {"status": "matched", "best_candidate": {"confidence_label": "high", "confidence_score": 91, "price": 118000, "model_name": "Golf GTI"}}
        return {"status": "no_match", "best_candidate": None}

    monkeypatch.setattr("app.services.fipe_prices_planning_service.resolve_listing_to_fipe_candidates", _resolver)
    before = db.query(FipePrice).count()
    out = build_fipe_price_plan(db, reference_month="2026-05", limit=100)
    after = db.query(FipePrice).count()
    assert out["planned_inserts_count"] == 1
    assert out["skipped_counts"]["no_match"] == 1
    assert before == after == 0
