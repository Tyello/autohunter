from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.models.car_listing import CarListing
from app.models.notification import Notification
from app.models.user import User
from app.models.wishlist import Wishlist
from app.services.notifications_cleanup_service import cleanup_old_notifications


def _mk_user(db, chat_id):
    user = User(id=uuid.uuid4(), telegram_chat_id=chat_id, username="tester", is_active=True)
    db.add(user)
    db.commit()
    return user


def _mk_wishlist(db, user_id):
    wishlist = Wishlist(id=uuid.uuid4(), user_id=user_id, query="civic si", is_active=True)
    db.add(wishlist)
    db.commit()
    return wishlist


def _mk_listing(db, external_id):
    listing = CarListing(
        id=uuid.uuid4(),
        source="olx",
        external_id=external_id,
        url=f"https://example.com/{external_id}",
        title="Honda Civic Si",
        price=Decimal("80000"),
        is_sold=False,
        updated_at=datetime.now(timezone.utc),
    )
    db.add(listing)
    db.commit()
    return listing


def _mk_notification(db, user_id, wishlist_id, listing_id, status, created_at, sent_at=None):
    notif = Notification(
        id=uuid.uuid4(),
        user_id=user_id,
        wishlist_id=wishlist_id,
        car_listing_id=listing_id,
        status=status,
        created_at=created_at,
        sent_at=sent_at,
    )
    db.add(notif)
    db.commit()
    return notif


def test_cleanup_never_deletes_anything(db):
    result = cleanup_old_notifications(db)
    assert result["deleted_suppressed"] == 0
    assert result["deleted_sent"] == 0
    assert result["deleted_failed"] == 0
    assert result["mode"] == "report_only_core_data_guardrail"


def test_cleanup_counts_old_suppressed_candidates(db):
    user = _mk_user(db, 9001)
    wishlist = _mk_wishlist(db, user.id)
    listing = _mk_listing(db, "ext-a")
    now = datetime.now(timezone.utc)

    _mk_notification(db, user.id, wishlist.id, listing.id, "suppressed", now - timedelta(days=10))
    _mk_notification(db, user.id, wishlist.id, listing.id, "suppressed", now - timedelta(days=1))

    result = cleanup_old_notifications(db, keep_suppressed_days=7)
    assert result["suppressed_candidates"] == 1


def test_cleanup_counts_old_sent_candidates_by_sent_at(db):
    user = _mk_user(db, 9002)
    wishlist = _mk_wishlist(db, user.id)
    listing = _mk_listing(db, "ext-b")
    now = datetime.now(timezone.utc)

    _mk_notification(db, user.id, wishlist.id, listing.id, "sent", now - timedelta(days=40), sent_at=now - timedelta(days=40))
    _mk_notification(db, user.id, wishlist.id, listing.id, "sent", now - timedelta(days=1), sent_at=now - timedelta(days=1))
    _mk_notification(db, user.id, wishlist.id, listing.id, "sent", now - timedelta(days=40), sent_at=None)

    result = cleanup_old_notifications(db, keep_sent_days=30)
    assert result["sent_candidates"] == 1


def test_cleanup_counts_old_failed_candidates(db):
    user = _mk_user(db, 9003)
    wishlist = _mk_wishlist(db, user.id)
    listing = _mk_listing(db, "ext-c")
    now = datetime.now(timezone.utc)

    _mk_notification(db, user.id, wishlist.id, listing.id, "failed", now - timedelta(days=100))
    _mk_notification(db, user.id, wishlist.id, listing.id, "failed", now - timedelta(days=1))

    result = cleanup_old_notifications(db, keep_failed_days=90)
    assert result["failed_candidates"] == 1
