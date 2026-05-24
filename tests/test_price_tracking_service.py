from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal

from app.models.car_listing import CarListing
from app.models.user import User
from app.models.wishlist import Wishlist
from app.models.wishlist_tracked_listing import WishlistTrackedListing
from app.services.price_tracking_service import sync_price_tracking_for_listings, sync_tracked_listing_price


def _mk(db, *, tracked_price=Decimal('100000'), listing_price=Decimal('100000')):
    u = User(id=uuid.uuid4(), telegram_chat_id=1, username='u', is_active=True)
    w = Wishlist(id=uuid.uuid4(), user_id=u.id, query='civic')
    listing = CarListing(id=uuid.uuid4(), source='olx', external_id='x', title='Civic', url='https://x', price=listing_price, location='SP', currency='BRL', extras={})
    tracked = WishlistTrackedListing(wishlist_id=w.id, car_listing_id=listing.id, slot=1, last_observed_price=tracked_price, price_drop_alert_enabled=True)
    db.add_all([u, w, listing, tracked])
    db.commit()
    return listing, tracked


def test_initial_sync_sets_initial_and_last_observed(db):
    listing, tracked = _mk(db, tracked_price=None, listing_price=Decimal('100000'))
    now = datetime.now(timezone.utc)
    res = sync_tracked_listing_price(db, tracked, listing, now=now)
    assert tracked.initial_price == Decimal('100000')
    assert tracked.last_observed_price == Decimal('100000')
    assert tracked.last_price_change_amount is None
    assert res.should_alert_price_drop is False


def test_price_drop_updates_fields_and_alert_flag(db):
    listing, tracked = _mk(db)
    listing.price = Decimal('95000')
    res = sync_tracked_listing_price(db, tracked, listing)
    assert tracked.last_observed_price == Decimal('95000')
    assert tracked.last_price_change_amount == Decimal('-5000')
    assert tracked.last_price_change_pct < 0
    assert tracked.last_price_change_direction == 'dropped'
    assert res.should_alert_price_drop is True


def test_price_up_no_drop_alert(db):
    listing, tracked = _mk(db)
    listing.price = Decimal('105000')
    res = sync_tracked_listing_price(db, tracked, listing)
    assert tracked.last_price_change_direction == 'increased'
    assert res.should_alert_price_drop is False


def test_same_price_only_updates_seen(db):
    listing, tracked = _mk(db)
    prev_seen = tracked.last_seen_at
    res = sync_tracked_listing_price(db, tracked, listing)
    assert tracked.last_price_change_amount is None
    assert tracked.last_seen_at != prev_seen
    assert res.should_alert_price_drop is False


def test_none_price_keeps_previous(db):
    listing, tracked = _mk(db)
    listing.price = None
    res = sync_tracked_listing_price(db, tracked, listing)
    assert tracked.last_observed_price == Decimal('100000')
    assert res.should_alert_price_drop is False


def test_dedupe_same_alert_price(db):
    listing, tracked = _mk(db)
    listing.price = Decimal('95000')
    tracked.last_price_drop_alert_price = Decimal('95000')
    res = sync_tracked_listing_price(db, tracked, listing)
    assert res.should_alert_price_drop is False


def test_batch_sync_only_known_tracking(db):
    listing, tracked = _mk(db)
    extra = CarListing(id=uuid.uuid4(), source='olx', external_id='y', title='Y', url='https://y', price=Decimal('120000'), location='SP', currency='BRL', extras={})
    db.add(extra)
    db.commit()
    listing.price = Decimal('99000')
    out = sync_price_tracking_for_listings(db, [listing, extra])
    assert len(out) == 1
    assert out[0].tracked_id == str(tracked.id)
