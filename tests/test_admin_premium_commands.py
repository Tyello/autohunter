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


def _mk_user(db, chat_id=123456):
    acc = Account(id=uuid.uuid4(), type="personal", name="acc", is_active=True)
    user = User(id=uuid.uuid4(), telegram_chat_id=chat_id, username="u", is_active=True, account_id=acc.id)
    db.add_all([acc, user])
    db.commit()
    return user


def _ctx(*args, send_message=None):
    async def _noop(**kwargs):
        return None
    return types.SimpleNamespace(args=list(args), bot=types.SimpleNamespace(send_message=send_message or _noop))


def test_admin_premium_activate_annual_and_365d(monkeypatch, db):
    user = _mk_user(db, 123456)
    db.add(Plan(code="premium", name="Premium", daily_alert_limit=10, max_wishlists=5, is_active=True))
    db.commit()
    monkeypatch.setattr(handlers_admin, "is_admin", lambda _cid: True)
    monkeypatch.setattr(handlers_admin, "SessionLocal", lambda: _SessionWrap(db))
    up = _Update()
    asyncio.run(handlers_admin.cmd_admin(up, _ctx("premium", "activate", "123456", "annual")))
    assert "Premium ativado" in up.message.sent[-1]
    assert "anual" in up.message.sent[-1]
    asyncio.run(handlers_admin.cmd_admin(up, _ctx("premium", "activate", "123456", "365d")))
    assert "Premium ativado" in up.message.sent[-1]
    active = db.query(Subscription).filter(Subscription.account_id == user.account_id, Subscription.status == "active").all()
    assert len(active) == 1


def test_admin_premium_activate_guards_and_errors(monkeypatch, db):
    _mk_user(db, 888001)
    db.add(Plan(code="premium", name="Premium", daily_alert_limit=10, max_wishlists=5, is_active=True))
    db.commit()
    monkeypatch.setattr(handlers_admin, "SessionLocal", lambda: _SessionWrap(db))
    up = _Update(chat_id=1)
    monkeypatch.setattr(handlers_admin, "is_admin", lambda _cid: False)
    asyncio.run(handlers_admin.cmd_admin(up, _ctx("premium", "activate", "888001", "monthly")))
    assert "Sem permissão." in up.message.sent[-1]

    monkeypatch.setattr(handlers_admin, "is_admin", lambda _cid: True)
    asyncio.run(handlers_admin.cmd_admin(up, _ctx("premium", "activate", "999999", "monthly")))
    assert "Usuário não encontrado." in up.message.sent[-1]
    asyncio.run(handlers_admin.cmd_admin(up, _ctx("premium", "activate", "888001", "weird")))
    assert "Período inválido" in up.message.sent[-1]


def test_admin_premium_activate_missing_plan_and_status(monkeypatch, db):
    _mk_user(db, 777001)
    monkeypatch.setattr(handlers_admin, "is_admin", lambda _cid: True)
    monkeypatch.setattr(handlers_admin, "SessionLocal", lambda: _SessionWrap(db))
    up = _Update()
    asyncio.run(handlers_admin.cmd_admin(up, _ctx("premium", "activate", "777001", "annual")))
    assert "Plano premium não encontrado no banco" in up.message.sent[-1]

    db.add(Plan(code="premium", name="Premium", daily_alert_limit=10, max_wishlists=5, is_active=True))
    db.commit()
    asyncio.run(handlers_admin.cmd_admin(up, _ctx("premium", "activate", "777001", "annual")))
    asyncio.run(handlers_admin.cmd_admin(up, _ctx("premium", "status", "777001")))
    assert "Plano: premium" in up.message.sent[-1]
    assert "Válido até:" in up.message.sent[-1]
