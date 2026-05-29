from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from app.models.account import Account
from app.models.plan import Plan
from app.models.subscription import Subscription
from app.models.user import User
from app.services.wishlists_service import get_user_plan_snapshot, add_wishlist
from app.models.wishlist import Wishlist


def test_get_user_plan_snapshot_with_active_premium_subscription(db):
    acc = Account(id=uuid.uuid4(), type="personal", name="acc", is_active=True)
    user = User(
        id=uuid.uuid4(),
        telegram_chat_id=990001,
        username="premium_user",
        is_active=True,
        account_id=acc.id,
    )
    free = Plan(code="free", name="Free", daily_alert_limit=5, max_wishlists=2, is_active=True)
    premium = Plan(code="premium", name="Premium", daily_alert_limit=999, max_wishlists=999, is_active=True)
    db.add_all([acc, user, free, premium])
    db.commit()

    sub = Subscription(account_id=acc.id, plan_id=premium.id, status="active", source="seed")
    db.add(sub)
    db.commit()

    snap = get_user_plan_snapshot(db, user.id)
    assert snap["plan_code"] == "premium"
    assert snap["max_wishlists"] == 999
    assert snap["daily_notifications_per_wishlist"] == 999
    assert snap["daily_alert_limit"] == 999


def test_get_user_plan_snapshot_without_active_subscription_uses_free_capabilities(db):
    acc = Account(id=uuid.uuid4(), type="personal", name="acc-free", is_active=True)
    user = User(
        id=uuid.uuid4(),
        telegram_chat_id=990002,
        username="free_user",
        is_active=True,
        account_id=acc.id,
    )
    db.add_all([acc, user])
    db.commit()

    snap = get_user_plan_snapshot(db, user.id)
    assert snap["plan_code"] == "free"
    assert snap["max_wishlists"] == 2
    assert snap["daily_notifications_per_wishlist"] == 5
    assert snap["daily_alert_limit"] == 5


def test_get_user_plan_snapshot_expired_premium_falls_back_to_free(db):
    acc = Account(id=uuid.uuid4(), type="personal", name="acc-exp", is_active=True)
    user = User(id=uuid.uuid4(), telegram_chat_id=990003, username="expired_user", is_active=True, account_id=acc.id)
    premium = Plan(code="premium", name="Premium", daily_alert_limit=15, max_wishlists=10, is_active=True)
    db.add_all([acc, user, premium]); db.commit()
    db.add(Subscription(account_id=acc.id, plan_id=premium.id, status="active", source="seed", current_period_end=datetime.now(timezone.utc) - timedelta(days=1)))
    db.commit()
    snap = get_user_plan_snapshot(db, user.id)
    assert snap["plan_code"] == "free"


def test_get_user_plan_snapshot_naive_current_period_end_future_keeps_premium(db):
    acc = Account(id=uuid.uuid4(), type="personal", name="acc-naive-future", is_active=True)
    user = User(id=uuid.uuid4(), telegram_chat_id=990004, username="naive_future", is_active=True, account_id=acc.id)
    premium = Plan(code="premium", name="Premium", daily_alert_limit=15, max_wishlists=10, is_active=True)
    db.add_all([acc, user, premium]); db.commit()
    naive_future = datetime.utcnow() + timedelta(days=2)
    db.add(Subscription(account_id=acc.id, plan_id=premium.id, status="active", source="seed", current_period_end=naive_future))
    db.commit()
    snap = get_user_plan_snapshot(db, user.id)
    assert snap["plan_code"] == "premium"


def test_get_user_plan_snapshot_uses_ends_at_when_current_period_end_missing(db):
    acc = Account(id=uuid.uuid4(), type="personal", name="acc-ends-at", is_active=True)
    user = User(id=uuid.uuid4(), telegram_chat_id=990005, username="ends_at_user", is_active=True, account_id=acc.id)
    premium = Plan(code="premium", name="Premium", daily_alert_limit=15, max_wishlists=10, is_active=True)
    db.add_all([acc, user, premium]); db.commit()
    future = datetime.now(timezone.utc) + timedelta(days=5)
    db.add(Subscription(account_id=acc.id, plan_id=premium.id, status="active", source="seed", ends_at=future))
    db.commit()
    snap = get_user_plan_snapshot(db, user.id)
    assert snap["plan_code"] == "premium"
    assert snap["current_period_end"] == future


def test_get_user_plan_snapshot_naive_current_period_end_past_falls_back_to_free(db):
    acc = Account(id=uuid.uuid4(), type="personal", name="acc-naive-past", is_active=True)
    user = User(id=uuid.uuid4(), telegram_chat_id=990006, username="naive_past", is_active=True, account_id=acc.id)
    premium = Plan(code="premium", name="Premium", daily_alert_limit=15, max_wishlists=10, is_active=True)
    db.add_all([acc, user, premium]); db.commit()
    naive_past = datetime.utcnow() - timedelta(days=2)
    db.add(Subscription(account_id=acc.id, plan_id=premium.id, status="active", source="seed", current_period_end=naive_past))
    db.commit()
    snap = get_user_plan_snapshot(db, user.id)
    assert snap["plan_code"] == "free"


def test_paused_wishlist_still_counts_against_free_limit(db, monkeypatch):
    user = User(id=uuid.uuid4(), telegram_chat_id=999001, username="limitfree", is_active=True)
    db.add(user); db.commit()
    db.add_all([
        Wishlist(id=uuid.uuid4(), user_id=user.id, query="civic", is_active=True),
        Wishlist(id=uuid.uuid4(), user_id=user.id, query="corolla", is_active=False),
    ])
    db.commit()
    monkeypatch.setattr("app.services.wishlists_service.trigger_initial_run_for_wishlist", lambda *_args, **_kwargs: {"triggered": 0})
    ok, msg = add_wishlist(db, user.id, "audi a3")
    assert ok is False
    assert "limite" in msg.lower()


def test_soft_deleted_wishlist_does_not_count_against_free_limit(db, monkeypatch):
    from app.services.wishlists_service import list_wishlists, remove_wishlist

    user = User(id=uuid.uuid4(), telegram_chat_id=999008, username="softlimit", is_active=True)
    db.add(user)
    db.commit()
    monkeypatch.setattr("app.services.wishlists_service.trigger_initial_run_for_wishlist", lambda *_args, **_kwargs: {"triggered": 0})

    assert add_wishlist(db, user.id, "civic")[0] is True
    assert add_wishlist(db, user.id, "corolla")[0] is True
    ok, msg = add_wishlist(db, user.id, "audi a3")
    assert ok is False
    assert "limite" in msg.lower()

    ok, _msg = remove_wishlist(db, user.id, 1)
    assert ok is True
    assert len(list_wishlists(db, user.id)) == 1

    ok, msg = add_wishlist(db, user.id, "audi a3")
    assert ok is True, msg
    assert len(list_wishlists(db, user.id)) == 2
