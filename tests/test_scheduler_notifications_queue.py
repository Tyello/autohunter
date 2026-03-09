from __future__ import annotations

import uuid

from app.models.car_listing import CarListing
from app.models.notification import Notification
from app.models.user import User
from app.models.wishlist import Wishlist
from app.scheduler.jobs import queue_notifications_for_new_listings


def _mk_user(db, chat_id: int) -> User:
    u = User(id=uuid.uuid4(), telegram_chat_id=chat_id, username=f"u{chat_id}", is_active=True)
    db.add(u)
    db.commit()
    return u


def _mk_listing(db, external_id: str) -> CarListing:
    l = CarListing(
        source="olx",
        external_id=external_id,
        title="Civic",
        url=f"https://example/{external_id}",
        price=90000,
    )
    db.add(l)
    db.commit()
    return l


def test_queue_notifications_for_new_listings_queues_only_missing_pairs(db):
    user = _mk_user(db, 1001)
    wishlist = Wishlist(user_id=user.id, query="civic", is_active=True)
    db.add(wishlist)
    db.commit()

    listing_a = _mk_listing(db, "A")
    listing_b = _mk_listing(db, "B")

    # Existing notification must be deduped.
    db.add(Notification(user_id=user.id, wishlist_id=wishlist.id, car_listing_id=listing_a.id, status="queued"))
    db.commit()

    queue_notifications_for_new_listings(db, component="test", new_listing_ids=[listing_a.id, listing_b.id])

    rows = db.query(Notification).filter(Notification.wishlist_id == wishlist.id).all()
    listing_ids = {r.car_listing_id for r in rows}
    assert len(rows) == 2
    assert listing_ids == {listing_a.id, listing_b.id}


def test_queue_notifications_for_new_listings_ignores_inactive_wishlists(db):
    user = _mk_user(db, 1002)
    inactive_wishlist = Wishlist(user_id=user.id, query="jetta", is_active=False)
    db.add(inactive_wishlist)
    db.commit()

    listing = _mk_listing(db, "C")

    queue_notifications_for_new_listings(db, component="test", new_listing_ids=[listing.id])

    rows = db.query(Notification).all()
    assert rows == []
