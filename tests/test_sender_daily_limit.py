from __future__ import annotations

import uuid
from decimal import Decimal

from app.models.car_listing import CarListing
from app.models.notification import Notification
from app.models.user import User
from app.models.wishlist import Wishlist
from app.scheduler.jobs_send import send_queued_notifications


def _seed_base(db):
    user = User(id=uuid.uuid4(), telegram_chat_id=123456, username="test", is_active=True)
    wl = Wishlist(user_id=user.id, query="civic si", is_active=True)
    listing = CarListing(
        source="olx",
        external_id="OLX1",
        title="Honda Civic SI 1994",
        url="https://www.olx.com.br/1",
        price=Decimal("32000"),
        currency="BRL",
    )
    db.add_all([user, wl, listing])
    db.commit()

    n = Notification(user_id=user.id, wishlist_id=wl.id, car_listing_id=listing.id, status="queued")
    db.add(n)
    db.commit()
    db.refresh(n)

    return user, wl, listing, n


def test_sender_marks_sent_when_allowed(db, monkeypatch):
    _user, _wl, listing, n = _seed_base(db)

    monkeypatch.setattr("app.scheduler.jobs_send.count_sent_today", lambda *_: 0)
    monkeypatch.setattr("app.scheduler.jobs_send.get_active_subscription_limit_for_user", lambda *_: 10)

    sent_calls = []

    def _sender_fn(notification, car_listing, user):
        sent_calls.append((notification.id, car_listing.external_id, user.telegram_chat_id))

    sent = send_queued_notifications(db, component="test", sender_fn=_sender_fn)
    assert sent == 1
    assert len(sent_calls) == 1

    row = db.query(Notification).filter(Notification.id == n.id).one()
    assert row.status == "sent"
    assert row.sent_at is not None
    assert row.car_listing.external_id == listing.external_id


def test_sender_suppresses_when_daily_limit_reached_and_sends_notice_once(db, monkeypatch):
    user, _wl, _listing, n = _seed_base(db)

    monkeypatch.setattr("app.scheduler.jobs_send.count_sent_today", lambda *_: 10)
    monkeypatch.setattr("app.scheduler.jobs_send.should_send_daily_limit_notice", lambda *_: True)
    monkeypatch.setattr("app.scheduler.jobs_send.get_active_subscription_limit_for_user", lambda *_: 10)

    notice_calls = []

    def _fake_notice_http(u, limit):
        notice_calls.append((u.id, limit))
        return True

    monkeypatch.setattr("app.scheduler.jobs_send.send_daily_limit_notice_http", _fake_notice_http)

    def _sender_fn(*_args, **_kwargs):
        raise AssertionError("sender_fn must NOT be called when daily limit is reached")

    sent = send_queued_notifications(db, component="test", sender_fn=_sender_fn)
    assert sent == 0

    row = db.query(Notification).filter(Notification.id == n.id).one()
    assert row.status == "suppressed"
    assert row.reason == "daily_limit_reached"

    # daily notice called once and timestamp updated
    assert len(notice_calls) == 1
    u2 = db.query(User).filter(User.id == user.id).one()
    assert u2.last_daily_limit_notice_at is not None


def test_sender_uses_per_user_budget_cache_within_batch(db, monkeypatch):
    _user, _wl, _listing, _n1 = _seed_base(db)
    n2 = Notification(user_id=_user.id, wishlist_id=_wl.id, car_listing_id=_listing.id, status="queued")
    db.add(n2)
    db.commit()

    calls = {"count": 0, "limit": 0, "sender": 0}

    def _count(*_args, **_kwargs):
        calls["count"] += 1
        return 1

    def _limit(*_args, **_kwargs):
        calls["limit"] += 1
        return 2

    monkeypatch.setattr("app.scheduler.jobs_send.count_sent_today", _count)
    monkeypatch.setattr("app.scheduler.jobs_send.get_active_subscription_limit_for_user", _limit)
    monkeypatch.setattr("app.scheduler.jobs_send.should_send_daily_limit_notice", lambda *_: False)

    def _sender_fn(*_args, **_kwargs):
        calls["sender"] += 1

    sent = send_queued_notifications(db, component="test", sender_fn=_sender_fn)

    assert sent == 1
    assert calls == {"count": 1, "limit": 1, "sender": 1}
    sent_rows = db.query(Notification).filter(Notification.status == "sent").all()
    suppressed_rows = db.query(Notification).filter(Notification.status == "suppressed").all()
    assert len(sent_rows) == 1
    assert len(suppressed_rows) == 1
    assert suppressed_rows[0].reason == "daily_limit_reached"


def test_daily_limit_notice_reuses_cached_limit(db, monkeypatch):
    _user, _wl, _listing, _n = _seed_base(db)

    calls = {"limit": 0}

    monkeypatch.setattr("app.scheduler.jobs_send.count_sent_today", lambda *_: 10)

    def _limit(*_args, **_kwargs):
        calls["limit"] += 1
        return 10

    monkeypatch.setattr("app.scheduler.jobs_send.get_active_subscription_limit_for_user", _limit)
    monkeypatch.setattr("app.scheduler.jobs_send.should_send_daily_limit_notice", lambda *_: True)

    notice_limits = []
    monkeypatch.setattr("app.scheduler.jobs_send.send_daily_limit_notice_http", lambda _u, limit: notice_limits.append(limit) or True)

    sent = send_queued_notifications(db, component="test", sender_fn=lambda *_args, **_kwargs: None)
    assert sent == 0
    assert calls["limit"] == 1
    assert notice_limits == [10]
