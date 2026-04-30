from __future__ import annotations

import uuid
from decimal import Decimal

from app.models.car_listing import CarListing
from app.models.notification import Notification
from app.models.user import User
from app.models.wishlist import Wishlist
from app.models.wishlist_tracked_listing import WishlistTrackedListing
from app.services.wishlist_tracking_service import evaluate_price_drop_alert, set_price_drop_alert_enabled


def _mk(db):
    u = User(id=uuid.uuid4(), telegram_chat_id=1, username='u', is_active=True)
    w = Wishlist(id=uuid.uuid4(), user_id=u.id, query='civic')
    l = CarListing(id=uuid.uuid4(), source='olx', external_id='x', title='Civic', url='https://x', price=Decimal('90000'), location='SP', currency='BRL', extras={})
    t = WishlistTrackedListing(wishlist_id=w.id, car_listing_id=l.id, slot=1, initial_price=Decimal('100000'), last_observed_price=Decimal('90000'), last_price_change_amount=Decimal('-10000'), last_price_change_pct=Decimal('-0.1'), last_price_change_direction='dropped', price_drop_alert_enabled=False)
    db.add_all([u, w, l, t])
    db.commit()
    return u, w, l, t


def test_opt_in_toggle_and_drop_alert_queue(db):
    u, _w, _l, t = _mk(db)
    ok, _ = set_price_drop_alert_enabled(db, user_id=u.id, wishlist_index=1, slot=1, enabled=True)
    assert ok is True
    assert evaluate_price_drop_alert(db, t, {'direction': 'dropped'}) is True
    assert db.query(Notification).filter(Notification.reason == 'tracked_price_drop').count() == 1
    assert evaluate_price_drop_alert(db, t, {'direction': 'dropped'}) is False


def test_no_alert_on_increase_or_optout(db):
    _u, _w, _l, t = _mk(db)
    assert evaluate_price_drop_alert(db, t, {'direction': 'dropped'}) is False
    t.price_drop_alert_enabled = True
    t.last_price_change_amount = Decimal('1000')
    assert evaluate_price_drop_alert(db, t, {'direction': 'increased'}) is False
