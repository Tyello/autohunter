from __future__ import annotations

import uuid
from decimal import Decimal

from app.models.car_listing import CarListing
from app.models.user import User
from app.models.wishlist import Wishlist
from app.models.wishlist_tracked_listing import WishlistTrackedListing
from app.services.wishlist_tracking_service import refresh_tracked_listing_snapshot


def _mk_tracking(db, price=Decimal('100000')):
    user = User(id=uuid.uuid4(), telegram_chat_id=9090, username='u9090', is_active=True)
    wl = Wishlist(id=uuid.uuid4(), user_id=user.id, query='civic')
    listing = CarListing(
        id=uuid.uuid4(), source='olx', external_id='x', title='Carro', url='https://x',
        price=price, location='SP', currency='BRL', extras={}
    )
    tracked = WishlistTrackedListing(wishlist_id=wl.id, car_listing_id=listing.id, slot=1, last_observed_price=price)
    db.add_all([user, wl, listing, tracked])
    db.commit()
    return listing, tracked


def test_refresh_unchanged_price(db):
    listing, tracked = _mk_tracking(db)
    stats = refresh_tracked_listing_snapshot(db, tracked, listing)
    assert stats['direction'] == 'unchanged'


def test_refresh_price_dropped(db):
    listing, tracked = _mk_tracking(db)
    listing.price = Decimal('90000')
    stats = refresh_tracked_listing_snapshot(db, tracked, listing)
    assert stats['direction'] == 'dropped'
    assert tracked.last_price_change_amount == Decimal('-10000')


def test_refresh_price_increased(db):
    listing, tracked = _mk_tracking(db)
    listing.price = Decimal('110000')
    stats = refresh_tracked_listing_snapshot(db, tracked, listing)
    assert stats['direction'] == 'increased'
    assert tracked.last_price_change_amount == Decimal('10000')


def test_refresh_handles_orphan_and_none_price(db):
    _listing, tracked = _mk_tracking(db, price=Decimal('100000'))
    tracked.car_listing_id = None
    db.commit()
    stats = refresh_tracked_listing_snapshot(db, tracked, None)
    assert stats['status'] == 'orphan'
