from datetime import datetime, timedelta, timezone
import uuid

from app.models.account import Account
from app.models.plan import Plan
from app.models.subscription import Subscription
from app.models.user import User
from app.services.premium_subscription_service import activate_manual_premium, expire_due_premium_subscriptions
from app.services.wishlists_service import get_user_plan_snapshot


def _mk_user(db, chat_id=111):
    acc = Account(id=uuid.uuid4(), type="personal", name="acc", is_active=True)
    user = User(id=uuid.uuid4(), telegram_chat_id=chat_id, username="u", is_active=True, account_id=acc.id)
    db.add_all([acc, user])
    db.commit()
    return user


def test_activate_manual_premium_and_expire(db):
    user = _mk_user(db)
    db.add(Plan(code="free", name="Free", daily_alert_limit=5, max_wishlists=2, is_active=True))
    db.add(Plan(code="premium", name="Premium", daily_alert_limit=10, max_wishlists=5, is_active=True))
    db.commit()
    result = activate_manual_premium(db, user.id, "monthly", activated_by="adm")
    assert result.ok is True
    snap = get_user_plan_snapshot(db, user.id)
    assert snap["plan_code"] == "premium"
    assert snap.get("current_period_end") is not None

    sub = db.query(Subscription).filter(Subscription.account_id == user.account_id, Subscription.status == "active").first()
    sub.current_period_end = datetime.now(timezone.utc) - timedelta(days=1)
    db.commit()
    expired = expire_due_premium_subscriptions(db)
    assert expired.expired_count == 1
    snap2 = get_user_plan_snapshot(db, user.id)
    assert snap2["plan_code"] == "free"
