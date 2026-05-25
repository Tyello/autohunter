from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.models.car_listing import CarListing
from app.models.notification import Notification
from app.models.user import User
from app.models.wishlist import Wishlist
from app.repositories.car_listings_repo import _fallback_upsert_without_constraint
from app.services.cross_source_dedupe_service import (
    compute_cross_source_fingerprint,
    evaluate_cross_source_notification_dedupe,
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


def _seed_user_wishlist(db):
    chat_id = int(str(uuid.uuid4().int)[:8])
    user = User(id=uuid.uuid4(), telegram_chat_id=chat_id, username=f"dedupe-u-{chat_id}", is_active=True)
    wl = Wishlist(user_id=user.id, query="civic", is_active=True)
    db.add_all([user, wl])
    db.flush()
    return user, wl


def test_eval_without_fingerprint_returns_false(db):
    user, wl = _seed_user_wishlist(db)
    listing = CarListing(source="olx", external_id="a", title="x", url="https://x")
    out = evaluate_cross_source_notification_dedupe(db, user_id=user.id, wishlist_id=wl.id, listing=listing)
    assert out["should_suppress"] is False


def test_eval_suppresses_cross_source_match(db):
    user, wl = _seed_user_wishlist(db)
    fp = compute_cross_source_fingerprint(_base_listing(source="olx", external_id="x1"))
    old = CarListing(source="olx", external_id="x1", title="a", url="https://olx/x1", cross_source_fingerprint=fp)
    new = CarListing(source="mercadolivre", external_id="x2", title="b", url="https://ml/x2", cross_source_fingerprint=fp)
    db.add_all([old, new]); db.flush()
    db.add(Notification(user_id=user.id, wishlist_id=wl.id, car_listing_id=old.id, status="sent", next_attempt_at=datetime.now(timezone.utc)))
    db.commit()
    out = evaluate_cross_source_notification_dedupe(db, user_id=user.id, wishlist_id=wl.id, listing=new)
    assert out["should_suppress"] is True


def test_eval_does_not_suppress_same_source_or_other_user_wishlist_status_or_window(db):
    user, wl = _seed_user_wishlist(db)
    other_user, other_wl = _seed_user_wishlist(db)
    _, clean_wl = _seed_user_wishlist(db)
    fp = compute_cross_source_fingerprint(_base_listing(source="olx", external_id="x1"))
    base = CarListing(source="olx", external_id="x1", title="a", url="https://olx/x1", cross_source_fingerprint=fp)
    same_source = CarListing(source="olx", external_id="x2", title="b", url="https://olx/x2", cross_source_fingerprint=fp)
    diff_source = CarListing(source="mercadolivre", external_id="x3", title="c", url="https://ml/x3", cross_source_fingerprint=fp)
    db.add_all([base, same_source, diff_source]); db.flush()
    stale = Notification(user_id=user.id, wishlist_id=wl.id, car_listing_id=base.id, status="sent", next_attempt_at=datetime.now(timezone.utc), created_at=datetime.now(timezone.utc) - timedelta(days=60))
    wrong_status = Notification(user_id=user.id, wishlist_id=wl.id, car_listing_id=base.id, status="failed", next_attempt_at=datetime.now(timezone.utc))
    other_wl_notif = Notification(user_id=user.id, wishlist_id=other_wl.id, car_listing_id=base.id, status="sent", next_attempt_at=datetime.now(timezone.utc))
    other_user_notif = Notification(user_id=other_user.id, wishlist_id=wl.id, car_listing_id=base.id, status="sent", next_attempt_at=datetime.now(timezone.utc))
    db.add_all([stale, wrong_status, other_wl_notif, other_user_notif]); db.commit()
    assert evaluate_cross_source_notification_dedupe(db, user_id=user.id, wishlist_id=wl.id, listing=same_source)["should_suppress"] is False
    assert evaluate_cross_source_notification_dedupe(db, user_id=user.id, wishlist_id=clean_wl.id, listing=diff_source)["should_suppress"] is False
    assert evaluate_cross_source_notification_dedupe(db, user_id=other_user.id, wishlist_id=clean_wl.id, listing=diff_source)["should_suppress"] is False
    assert evaluate_cross_source_notification_dedupe(db, user_id=user.id, wishlist_id=wl.id, listing=diff_source, window_days=30)["should_suppress"] is False
