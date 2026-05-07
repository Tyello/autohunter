from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from app.models.account import Account
from app.models.plan import Plan
from app.models.subscription import Subscription
from app.models.user import User
from app.services.wishlists_service import get_user_plan_snapshot


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
