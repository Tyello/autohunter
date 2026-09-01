from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.models.account import Account
from app.models.car_listing import CarListing
from app.models.notification import Notification
from app.models.plan import Plan
from app.models.subscription import Subscription
from app.models.user import User
from app.models.wishlist import Wishlist
from app.services.limits_service import (
    count_notifications_sent_last_n_days,
    count_sent_today,
    get_active_subscription_limit_for_user,
    should_send_daily_limit_notice,
)


def _mk_user(db, chat_id, account_id=None):
    user = User(id=uuid.uuid4(), telegram_chat_id=chat_id, username=f"u{chat_id}", is_active=True, account_id=account_id)
    db.add(user)
    db.commit()
    return user


def _mk_account(db):
    acc = Account(id=uuid.uuid4(), type="personal", name="acc", is_active=True)
    db.add(acc)
    db.commit()
    return acc


def _mk_plan(db, code="premium", daily_alert_limit=15):
    plan = Plan(code=code, name=code, daily_alert_limit=daily_alert_limit, max_wishlists=10, is_active=True)
    db.add(plan)
    db.commit()
    return plan


def _mk_subscription(db, account_id, plan_id, status="active", override=None):
    sub = Subscription(id=uuid.uuid4(), account_id=account_id, plan_id=plan_id, status=status, daily_alert_limit_override=override)
    db.add(sub)
    db.commit()
    return sub


def _mk_wishlist(db, user_id, query="civic si"):
    wishlist = Wishlist(id=uuid.uuid4(), user_id=user_id, query=query, is_active=True)
    db.add(wishlist)
    db.commit()
    return wishlist


def _mk_listing(db, external_id="ext-1"):
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


def _mk_notification(db, user_id, wishlist_id, car_listing_id, status="sent", sent_at=None):
    notif = Notification(
        id=uuid.uuid4(),
        user_id=user_id,
        wishlist_id=wishlist_id,
        car_listing_id=car_listing_id,
        status=status,
        sent_at=sent_at,
    )
    db.add(notif)
    db.commit()
    return notif


def test_should_send_daily_limit_notice_true_when_never_notified():
    user = type("U", (), {"last_daily_limit_notice_at": None})()
    assert should_send_daily_limit_notice(user) is True


def test_should_send_daily_limit_notice_false_same_local_day():
    now = datetime.now(timezone.utc)
    user = type("U", (), {"last_daily_limit_notice_at": now})()
    assert should_send_daily_limit_notice(user) is False


def test_should_send_daily_limit_notice_true_after_day_boundary():
    stale = datetime.now(timezone.utc) - timedelta(days=2)
    user = type("U", (), {"last_daily_limit_notice_at": stale})()
    assert should_send_daily_limit_notice(user) is True


def test_count_sent_today_only_counts_sent_status_within_window(db):
    user = _mk_user(db, 5001)
    wishlist = _mk_wishlist(db, user.id)
    listing = _mk_listing(db, "listing-a")
    now = datetime.now(timezone.utc)

    _mk_notification(db, user.id, wishlist.id, listing.id, status="sent", sent_at=now)
    _mk_notification(db, user.id, wishlist.id, listing.id, status="failed", sent_at=now)

    assert count_sent_today(db, user.id) == 1


def test_count_sent_today_excludes_notifications_outside_window(db):
    user = _mk_user(db, 5002)
    wishlist = _mk_wishlist(db, user.id)
    listing = _mk_listing(db, "listing-b")
    old = datetime.now(timezone.utc) - timedelta(days=3)

    _mk_notification(db, user.id, wishlist.id, listing.id, status="sent", sent_at=old)

    assert count_sent_today(db, user.id) == 0


def test_get_active_subscription_limit_defaults_when_no_account(db):
    user = _mk_user(db, 5003, account_id=None)
    assert get_active_subscription_limit_for_user(db, user.id) == 10


def test_get_active_subscription_limit_defaults_when_no_active_subscription(db):
    account = _mk_account(db)
    user = _mk_user(db, 5004, account_id=account.id)
    assert get_active_subscription_limit_for_user(db, user.id) == 10


def test_get_active_subscription_limit_uses_plan_limit(db):
    account = _mk_account(db)
    plan = _mk_plan(db, "premium", daily_alert_limit=25)
    _mk_subscription(db, account.id, plan.id, status="active")
    user = _mk_user(db, 5005, account_id=account.id)

    assert get_active_subscription_limit_for_user(db, user.id) == 25


def test_get_active_subscription_limit_override_takes_priority(db):
    account = _mk_account(db)
    plan = _mk_plan(db, "premium", daily_alert_limit=25)
    _mk_subscription(db, account.id, plan.id, status="active", override=7)
    user = _mk_user(db, 5006, account_id=account.id)

    assert get_active_subscription_limit_for_user(db, user.id) == 7


def test_get_active_subscription_limit_ignores_inactive_subscription(db):
    account = _mk_account(db)
    plan = _mk_plan(db, "premium", daily_alert_limit=25)
    _mk_subscription(db, account.id, plan.id, status="canceled")
    user = _mk_user(db, 5007, account_id=account.id)

    assert get_active_subscription_limit_for_user(db, user.id) == 10


def test_count_notifications_sent_last_n_days(db):
    user = _mk_user(db, 5008)
    wishlist = _mk_wishlist(db, user.id)
    listing = _mk_listing(db, "listing-c")
    now = datetime.now(timezone.utc)

    _mk_notification(db, user.id, wishlist.id, listing.id, status="sent", sent_at=now - timedelta(days=1))
    _mk_notification(db, user.id, wishlist.id, listing.id, status="sent", sent_at=now - timedelta(days=10))
    _mk_notification(db, user.id, wishlist.id, listing.id, status="failed", sent_at=now - timedelta(days=1))

    assert count_notifications_sent_last_n_days(db, user.id, days=7) == 1
