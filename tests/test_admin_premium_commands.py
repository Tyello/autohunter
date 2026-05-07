import asyncio
import types
import uuid

from app.bot import handlers_admin
from app.models.account import Account
from app.models.plan import Plan
from app.models.user import User


class _Msg:
    def __init__(self):
        self.sent = []

    async def reply_text(self, txt, **kwargs):
        self.sent.append(txt)


class _Update:
    def __init__(self, chat_id=999):
        self.effective_chat = types.SimpleNamespace(id=chat_id)
        self.effective_user = types.SimpleNamespace(id=chat_id, username="adm")
        self.message = _Msg()


class _SessionWrap:
    def __init__(self, db):
        self.db = db
    def __enter__(self):
        return self.db
    def __exit__(self, *_):
        return False


def test_admin_premium_activate_monthly(monkeypatch, db):
    acc = Account(id=uuid.uuid4(), type="personal", name="acc", is_active=True)
    user = User(id=uuid.uuid4(), telegram_chat_id=123456, username="u", is_active=True, account_id=acc.id)
    db.add_all([acc, user, Plan(code="premium", name="Premium", daily_alert_limit=10, max_wishlists=5, is_active=True)])
    db.commit()
    monkeypatch.setattr(handlers_admin, "is_admin", lambda _cid: True)
    monkeypatch.setattr(handlers_admin, "SessionLocal", lambda: _SessionWrap(db))
    sent = {"n": 0}
    async def _send_message(**kwargs):
        sent["n"] += 1
    ctx = types.SimpleNamespace(args=["premium", "activate", "123456", "monthly"], bot=types.SimpleNamespace(send_message=_send_message))
    up = _Update()
    asyncio.run(handlers_admin.cmd_admin(up, ctx))
    assert "Premium ativado" in up.message.sent[-1]
    assert sent["n"] == 1
