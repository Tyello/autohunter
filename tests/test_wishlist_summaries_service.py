from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from app.models.car_listing import CarListing
from app.models.notification import Notification
from app.models.user import User
from app.models.wishlist import Wishlist
from app.services.wishlists_service import get_wishlist_summaries


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
