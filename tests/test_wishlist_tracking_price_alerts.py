from __future__ import annotations

import uuid
from decimal import Decimal
from datetime import datetime, timedelta, timezone

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


def test_dedupe_same_price_and_allow_new_lower_price_after_cooldown(db):
    _u, _w, _l, t = _mk(db)
    t.price_drop_alert_enabled = True
    assert evaluate_price_drop_alert(db, t, {'direction': 'dropped'}) is True
    assert evaluate_price_drop_alert(db, t, {'direction': 'dropped'}) is False

    t.last_price_drop_alert_at = datetime.now(timezone.utc) - timedelta(hours=25)
    t.last_observed_price = Decimal('85000')
    t.last_price_change_amount = Decimal('-5000')
    t.last_price_change_pct = Decimal('-0.055')
    assert evaluate_price_drop_alert(db, t, {'direction': 'dropped'}) is True


def test_queue_payload_contains_deterministic_fields(db):
    _u, _w, _l, t = _mk(db)
    t.price_drop_alert_enabled = True
    t.created_at = datetime.now(timezone.utc) - timedelta(days=5)
    t.last_price_change_at = datetime.now(timezone.utc) - timedelta(hours=2)
    t.last_seen_at = datetime.now(timezone.utc) - timedelta(hours=1)
    t.last_price_drop_alert_price = Decimal('95000')
    assert evaluate_price_drop_alert(db, t, {'direction': 'dropped'}) is True
    n = db.query(Notification).filter(Notification.reason == 'tracked_price_drop').first()
    assert n is not None
    assert n.score_breakdown["type"] == "tracked_price_drop"
    assert n.score_breakdown["slot"] == 1
    assert n.score_breakdown["current_price"] == 90000
    assert n.score_breakdown["previous_price"] == 100000
    assert n.score_breakdown["initial_price"] == 100000
    assert n.score_breakdown["tracked_since"] is not None
    assert n.score_breakdown["last_price_change_at"] is not None
    assert n.score_breakdown["last_seen_at"] is not None
    assert n.score_breakdown["total_drop_amount"] == 10000
    assert n.score_breakdown["total_drop_pct"] == 10.0
