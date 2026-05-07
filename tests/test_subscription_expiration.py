from datetime import datetime, timedelta, timezone
import uuid

from app.models.account import Account
from app.models.plan import Plan
from app.models.subscription import Subscription
from app.models.user import User
from app.scheduler import premium_expiration_job


class _SessionWrap:
    def __init__(self, db):
        self.db = db
    def __call__(self):
        return self.db


def test_job_expire_premium_subscriptions_respects_shutdown_guard(monkeypatch, db):
    called = {"n": 0}
    monkeypatch.setattr(premium_expiration_job, "is_shutdown_requested", lambda: True)
    monkeypatch.setattr(premium_expiration_job, "expire_due_premium_subscriptions", lambda _db: called.__setitem__("n", called["n"] + 1))
    premium_expiration_job.job_expire_premium_subscriptions()
    assert called["n"] == 0


def test_job_expire_premium_subscriptions_notify_failure_not_break(monkeypatch, db):
    acc = Account(id=uuid.uuid4(), type="personal", name="acc", is_active=True)
    usr = User(id=uuid.uuid4(), telegram_chat_id=9991, username="u", is_active=True, account_id=acc.id)
    plan = Plan(code="premium", name="Premium", daily_alert_limit=10, max_wishlists=5, is_active=True)
    db.add_all([acc, usr, plan])
    db.commit()
    db.add(
        Subscription(
            account_id=acc.id,
            plan_id=plan.id,
            status="active",
            source="manual",
            starts_at=datetime.now(timezone.utc) - timedelta(days=31),
            current_period_end=datetime.now(timezone.utc) - timedelta(days=1),
        )
    )
    db.commit()
    monkeypatch.setattr(premium_expiration_job, "is_shutdown_requested", lambda: False)
    monkeypatch.setattr(premium_expiration_job, "SessionLocal", _SessionWrap(db))
    monkeypatch.setattr(premium_expiration_job, "send_plain_text_to_user", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("fail")))
    premium_expiration_job.job_expire_premium_subscriptions()
    sub = db.query(Subscription).first()
    assert sub.status == "expired"
