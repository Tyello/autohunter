from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal

from app.models.car_listing import CarListing
from app.models.notification import Notification
from app.models.user import User
from app.models.wishlist import Wishlist
from app.services.notifications_service import mark_failed, mark_suppressed_reason


def _make_user(db, chat_id):
    user = User(id=uuid.uuid4(), telegram_chat_id=chat_id, username="tester", is_active=True)
    db.add(user)
    db.commit()
    return user


def _make_wishlist(db, user_id, query="civic si"):
    wishlist = Wishlist(id=uuid.uuid4(), user_id=user_id, query=query, is_active=True)
    db.add(wishlist)
    db.commit()
    return wishlist


def _make_listing(db, external_id="ext-1", price=Decimal("80000")):
    listing = CarListing(
        id=uuid.uuid4(),
        source="olx",
        external_id=external_id,
        url=f"https://example.com/{external_id}",
        title="Honda Civic Si",
        price=price,
        is_sold=False,
        updated_at=datetime.now(timezone.utc),
    )
    db.add(listing)
    db.commit()
    return listing


def _make_notification(db, user_id, wishlist_id, car_listing_id, status="processing"):
    notif = Notification(
        id=uuid.uuid4(),
        user_id=user_id,
        wishlist_id=wishlist_id,
        car_listing_id=car_listing_id,
        status=status,
        processing_started_at=datetime.now(timezone.utc),
        processing_owner="worker-1",
    )
    db.add(notif)
    db.commit()
    return notif


def test_mark_failed_sets_status_reason_and_clears_processing_state(db):
    user = _make_user(db, 3001)
    wishlist = _make_wishlist(db, user.id)
    listing = _make_listing(db, external_id="civic-fail")
    notif = _make_notification(db, user.id, wishlist.id, listing.id)

    mark_failed(db, notif.id, "boom: telegram timeout")

    db.refresh(notif)
    assert notif.status == "failed"
    assert notif.reason == "send_error"
    assert notif.error_message == "boom: telegram timeout"
    assert notif.processing_started_at is None
    assert notif.processing_owner is None


def test_mark_failed_truncates_error_message_to_5000_chars(db):
    user = _make_user(db, 3002)
    wishlist = _make_wishlist(db, user.id)
    listing = _make_listing(db, external_id="civic-fail-long")
    notif = _make_notification(db, user.id, wishlist.id, listing.id)

    mark_failed(db, notif.id, "x" * 6000)

    db.refresh(notif)
    assert len(notif.error_message) == 5000


def test_mark_suppressed_reason_sets_status_and_clears_error(db):
    user = _make_user(db, 3003)
    wishlist = _make_wishlist(db, user.id)
    listing = _make_listing(db, external_id="civic-suppressed")
    notif = _make_notification(db, user.id, wishlist.id, listing.id)
    notif.error_message = "stale error"
    db.commit()

    mark_suppressed_reason(db, notif.id, "daily_limit_reached")

    db.refresh(notif)
    assert notif.status == "suppressed"
    assert notif.reason == "daily_limit_reached"
    assert notif.error_message is None
    assert notif.processing_started_at is None
    assert notif.processing_owner is None
