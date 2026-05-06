from __future__ import annotations

import asyncio
import types
import uuid

from app.bot import handlers_admin
from app.models.account import Account
from app.models.plan import Plan
from app.models.subscription import Subscription
from app.models.user import User


class _Msg:
    def __init__(self):
        self.sent = []

    async def reply_text(self, txt, **kwargs):
        self.sent.append(txt)


class _Update:
    def __init__(self):
        self.effective_message = _Msg()


class _SessionWrap:
    def __init__(self, db):
        self._db = db

    def __enter__(self):
        return self._db

    def __exit__(self, *_args):
        return False


def _mk_user_with_sub(db, chat_id: int, plan_code: str):
    acc = Account(id=uuid.uuid4(), type="personal", name=f"acc-{chat_id}", is_active=True)
    user = User(id=uuid.uuid4(), telegram_chat_id=chat_id, username=f"u{chat_id}", is_active=True, account_id=acc.id)
    plan = Plan(code=plan_code, name=plan_code.title(), daily_alert_limit=10, max_wishlists=3, is_active=True)
    db.add_all([acc, user, plan])
    db.commit()
    db.add(Subscription(account_id=acc.id, plan_id=plan.id, status="active", source="seed"))
    db.commit()


def test_admin_users_renders_only_public_plan_labels(monkeypatch, db):
    _mk_user_with_sub(db, 101, "pro")
    _mk_user_with_sub(db, 102, "ultra")
    _mk_user_with_sub(db, 103, "premium")
    free_user = User(id=uuid.uuid4(), telegram_chat_id=104, username="u104", is_active=True, plan="free")
    db.add(free_user)
    db.commit()

    monkeypatch.setattr(handlers_admin, "SessionLocal", lambda: _SessionWrap(db))
    update = _Update()
    asyncio.run(handlers_admin._admin_users(update, []))
    text = update.effective_message.sent[-1]

    assert "plan=pro" not in text
    assert "plan=ultra" not in text
    assert "plan=paid" not in text
    assert "plan=premium" in text
    assert "plan=free" in text
    assert "/setplan <free|premium>" in text
