from datetime import datetime, timedelta, timezone
import uuid

from app.models.account import Account
from app.models.plan import Plan
from app.models.subscription import Subscription
from app.models.user import User
from app.services.premium_subscription_service import activate_manual_premium, expire_due_premium_subscriptions


def _mk_account_with_users(db, chat_ids):
    acc = Account(id=uuid.uuid4(), type="personal", name="acc", is_active=True)
    users = [
        User(id=uuid.uuid4(), telegram_chat_id=chat_id, username=f"u{chat_id}", is_active=True, account_id=acc.id)
        for chat_id in chat_ids
    ]
    db.add(acc)
    db.add_all(users)
    db.commit()
    return acc, users


def test_expire_due_premium_subscriptions_multi_user_account_no_dup(db):
    acc, users = _mk_account_with_users(db, [111, 222])
    premium = Plan(code="premium", name="Premium", daily_alert_limit=10, max_wishlists=5, is_active=True)
    db.add(premium)
    db.commit()
    sub = Subscription(
        account_id=acc.id,
        plan_id=premium.id,
        status="active",
        source="manual_mercado_pago",
        starts_at=datetime.now(timezone.utc) - timedelta(days=31),
        current_period_start=datetime.now(timezone.utc) - timedelta(days=31),
        current_period_end=datetime.now(timezone.utc) - timedelta(days=1),
    )
    db.add(sub)
    db.commit()
    result = expire_due_premium_subscriptions(db)
    db.refresh(sub)
    assert result.expired_count == 1
    assert sub.status == "expired"
    assert sorted(result.expired_chat_ids) == sorted([u.telegram_chat_id for u in users])


def test_expire_due_premium_subscriptions_keeps_active_when_still_valid(db):
    acc, _ = _mk_account_with_users(db, [333])
    premium = Plan(code="premium", name="Premium", daily_alert_limit=10, max_wishlists=5, is_active=True)
    db.add(premium)
    db.commit()
    sub = Subscription(
        account_id=acc.id,
        plan_id=premium.id,
        status="active",
        source="manual_mercado_pago",
        starts_at=datetime.now(timezone.utc),
        current_period_start=datetime.now(timezone.utc),
        current_period_end=datetime.now(timezone.utc) + timedelta(days=10),
    )
    db.add(sub)
    db.commit()
    result = expire_due_premium_subscriptions(db)
    db.refresh(sub)
    assert result.expired_count == 0
    assert sub.status == "active"


def test_activate_manual_premium_cancels_previous_active(db):
    acc, users = _mk_account_with_users(db, [444])
    user = users[0]
    premium = Plan(code="premium", name="Premium", daily_alert_limit=10, max_wishlists=5, is_active=True)
    db.add(premium)
    db.commit()
    old = Subscription(account_id=acc.id, plan_id=premium.id, status="active", source="manual", starts_at=datetime.now(timezone.utc))
    db.add(old)
    db.commit()
    result = activate_manual_premium(db, user.id, "annual", activated_by="admin")
    assert result.ok is True
    db.refresh(old)
    assert old.status == "canceled"
    active = db.query(Subscription).filter(Subscription.account_id == acc.id, Subscription.status == "active").all()
    assert len(active) == 1
