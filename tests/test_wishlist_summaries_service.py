from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from app.models.car_listing import CarListing
from app.models.notification import Notification
from app.models.user import User
from app.models.wishlist import Wishlist
from app.models.wishlist_filter import WishlistFilter
from app.services.wishlists_service import get_wishlist_summaries
from app.services import wishlists_service


def _mk_user(db) -> User:
    u = User(id=uuid.uuid4(), telegram_chat_id=123456, username="tester", is_active=True)
    db.add(u)
    db.commit()
    return u


def _mk_wishlist(db, user: User, query: str) -> Wishlist:
    wl = Wishlist(user_id=user.id, query=query, is_active=True)
    db.add(wl)
    db.commit()
    return wl


def _mk_listing(db, external_id: str) -> CarListing:
    listing = CarListing(source="olx", external_id=external_id, url=f"https://example.com/{external_id}")
    db.add(listing)
    db.commit()
    return listing


def _add_notification(db, *, user_id, wishlist_id, car_listing_id, status: str, sent_at: datetime | None):
    n = Notification(
        user_id=user_id,
        wishlist_id=wishlist_id,
        car_listing_id=car_listing_id,
        status=status,
        sent_at=sent_at,
    )
    db.add(n)
    db.commit()


def test_get_wishlist_summaries_notifications_24h_zero_when_none(db):
    user = _mk_user(db)
    _mk_wishlist(db, user, "civic")

    summaries = get_wishlist_summaries(db, user.id)

    assert len(summaries) == 1
    assert summaries[0]["notifications_24h_count"] == 0


def test_get_wishlist_summaries_counts_only_recent_sent(db):
    user = _mk_user(db)
    wl = _mk_wishlist(db, user, "civic")
    listing = _mk_listing(db, "a1")
    now = datetime.now(timezone.utc)

    _add_notification(
        db,
        user_id=user.id,
        wishlist_id=wl.id,
        car_listing_id=listing.id,
        status="sent",
        sent_at=now - timedelta(hours=1),
    )

    summaries = get_wishlist_summaries(db, user.id)

    assert summaries[0]["notifications_24h_count"] == 1


def test_get_wishlist_summaries_ignores_old_and_non_sent(db):
    user = _mk_user(db)
    wl = _mk_wishlist(db, user, "civic")
    listing_a = _mk_listing(db, "a1")
    listing_b = _mk_listing(db, "a2")
    now = datetime.now(timezone.utc)

    _add_notification(
        db,
        user_id=user.id,
        wishlist_id=wl.id,
        car_listing_id=listing_a.id,
        status="sent",
        sent_at=now - timedelta(hours=30),
    )
    _add_notification(
        db,
        user_id=user.id,
        wishlist_id=wl.id,
        car_listing_id=listing_b.id,
        status="suppressed",
        sent_at=now - timedelta(hours=1),
    )

    summaries = get_wishlist_summaries(db, user.id)

    assert summaries[0]["notifications_24h_count"] == 0


def test_get_wishlist_summaries_counts_are_separate_per_wishlist(db):
    user = _mk_user(db)
    wl_a = _mk_wishlist(db, user, "civic")
    wl_b = _mk_wishlist(db, user, "corolla")
    listing_a = _mk_listing(db, "a1")
    listing_b = _mk_listing(db, "a2")
    now = datetime.now(timezone.utc)

    _add_notification(
        db,
        user_id=user.id,
        wishlist_id=wl_a.id,
        car_listing_id=listing_a.id,
        status="sent",
        sent_at=now - timedelta(hours=2),
    )
    _add_notification(
        db,
        user_id=user.id,
        wishlist_id=wl_a.id,
        car_listing_id=listing_b.id,
        status="sent",
        sent_at=now - timedelta(hours=3),
    )
    _add_notification(
        db,
        user_id=user.id,
        wishlist_id=wl_b.id,
        car_listing_id=listing_b.id,
        status="sent",
        sent_at=now - timedelta(hours=4),
    )

    summaries = get_wishlist_summaries(db, user.id)

    by_query = {s["query"]: s for s in summaries}
    assert by_query["civic"]["notifications_24h_count"] == 2
    assert by_query["corolla"]["notifications_24h_count"] == 1


def test_wishlist_summaries_cache_hit_avoids_recompute(db, monkeypatch):
    user = _mk_user(db)
    _mk_wishlist(db, user, "civic")
    wishlists_service.invalidate_wishlist_summaries_cache()
    monkeypatch.setattr(wishlists_service.settings, "wishlist_summaries_cache_ttl_seconds", 10)
    calls = {"n": 0}
    original = wishlists_service._compute_wishlist_summaries

    def _wrapped(db_sess, user_id):
        calls["n"] += 1
        return original(db_sess, user_id)

    monkeypatch.setattr(wishlists_service, "_compute_wishlist_summaries", _wrapped)
    a = get_wishlist_summaries(db, user.id)
    b = get_wishlist_summaries(db, user.id)
    assert a == b
    assert calls["n"] == 1


def test_wishlist_summaries_cache_returns_copy(db, monkeypatch):
    user = _mk_user(db)
    _mk_wishlist(db, user, "civic")
    wishlists_service.invalidate_wishlist_summaries_cache()
    monkeypatch.setattr(wishlists_service.settings, "wishlist_summaries_cache_ttl_seconds", 10)
    first = get_wishlist_summaries(db, user.id)
    first[0]["query"] = "hacked"
    first[0]["filters"].append({"field": "x", "operator": "eq", "value": "y"})
    second = get_wishlist_summaries(db, user.id)
    assert second[0]["query"] == "civic"
    assert all(f.get("field") != "x" for f in second[0]["filters"])


def test_wishlist_summaries_cache_ttl_expiration_recomputes(db, monkeypatch):
    user = _mk_user(db)
    _mk_wishlist(db, user, "civic")
    wishlists_service.invalidate_wishlist_summaries_cache()
    monkeypatch.setattr(wishlists_service.settings, "wishlist_summaries_cache_ttl_seconds", 10)
    calls = {"n": 0}
    original = wishlists_service._compute_wishlist_summaries

    def _wrapped(db_sess, user_id):
        calls["n"] += 1
        return original(db_sess, user_id)

    monkeypatch.setattr(wishlists_service, "_compute_wishlist_summaries", _wrapped)
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    monkeypatch.setattr(wishlists_service, "_utcnow", lambda: base)
    get_wishlist_summaries(db, user.id)
    monkeypatch.setattr(wishlists_service, "_utcnow", lambda: base + timedelta(seconds=11))
    get_wishlist_summaries(db, user.id)
    assert calls["n"] == 2


def test_wishlist_summaries_invalidates_on_create_wishlist(db, monkeypatch):
    user = _mk_user(db)
    wishlists_service.invalidate_wishlist_summaries_cache()
    monkeypatch.setattr(wishlists_service.settings, "wishlist_summaries_cache_ttl_seconds", 10)
    get_wishlist_summaries(db, user.id)
    ok, _ = wishlists_service.add_wishlist(db, user.id, "civic", enqueue_initial_run=False)
    assert ok is True
    summaries = get_wishlist_summaries(db, user.id)
    assert any(s["query"] == "civic" for s in summaries)


def test_wishlist_summaries_invalidates_on_active_state(db, monkeypatch):
    user = _mk_user(db)
    _mk_wishlist(db, user, "civic")
    wishlists_service.invalidate_wishlist_summaries_cache()
    monkeypatch.setattr(wishlists_service.settings, "wishlist_summaries_cache_ttl_seconds", 10)
    get_wishlist_summaries(db, user.id)
    ok, _ = wishlists_service.set_wishlist_active_state(db, user.id, 1, False)
    assert ok is True
    summaries = get_wishlist_summaries(db, user.id)
    assert summaries[0]["is_active"] is False


def test_wishlist_summaries_invalidates_on_filter_add(db, monkeypatch):
    user = _mk_user(db)
    wl = _mk_wishlist(db, user, "civic")
    wishlists_service.invalidate_wishlist_summaries_cache()
    monkeypatch.setattr(wishlists_service.settings, "wishlist_summaries_cache_ttl_seconds", 10)
    get_wishlist_summaries(db, user.id)
    ok, _ = wishlists_service.add_filter(db, wl.id, "year", "gte", "2010")
    assert ok is True
    summaries = get_wishlist_summaries(db, user.id)
    assert summaries[0]["filters_count"] == 1


def test_wishlist_summaries_cache_disabled_recomputes(db, monkeypatch):
    user = _mk_user(db)
    _mk_wishlist(db, user, "civic")
    wishlists_service.invalidate_wishlist_summaries_cache()
    monkeypatch.setattr(wishlists_service.settings, "wishlist_summaries_cache_ttl_seconds", 0)
    calls = {"n": 0}
    original = wishlists_service._compute_wishlist_summaries

    def _wrapped(db_sess, user_id):
        calls["n"] += 1
        return original(db_sess, user_id)

    monkeypatch.setattr(wishlists_service, "_compute_wishlist_summaries", _wrapped)
    get_wishlist_summaries(db, user.id)
    get_wishlist_summaries(db, user.id)
    assert calls["n"] == 2
