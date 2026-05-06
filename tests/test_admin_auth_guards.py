import asyncio
import types
import uuid

from app.bot import handlers
from app.bot import handlers_admin
from app.bot import handlers_debug
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
    def __init__(self, chat_id=123, username="tester"):
        self.effective_chat = types.SimpleNamespace(id=chat_id)
        self.effective_user = types.SimpleNamespace(id=chat_id, username=username)
        self.message = _Msg()
        self.effective_message = self.message


def test_cmd_setplan_blocks_non_admin_without_side_effects(monkeypatch):
    update = _Update(chat_id=123)
    context = types.SimpleNamespace(args=["premium", "456"])

    async def _deny(_update):
        return False

    called = {"db": False}

    class _SessionFail:
        def __enter__(self):
            called["db"] = True
            raise AssertionError("DB should not be opened for unauthorized setplan")

        def __exit__(self, *_args):
            return False

    monkeypatch.setattr(handlers, "_ensure_admin", _deny)
    monkeypatch.setattr(handlers, "SessionLocal", lambda: _SessionFail())

    asyncio.run(handlers.cmd_setplan(update, context))
    assert called["db"] is False


def test_cmd_setlimit_blocks_non_admin_without_side_effects(monkeypatch):
    update = _Update(chat_id=123)
    context = types.SimpleNamespace(args=["10", "456"])

    async def _deny(_update):
        return False

    called = {"db": False}

    class _SessionFail:
        def __enter__(self):
            called["db"] = True
            raise AssertionError("DB should not be opened for unauthorized setlimit")

        def __exit__(self, *_args):
            return False

    monkeypatch.setattr(handlers, "_ensure_admin", _deny)
    monkeypatch.setattr(handlers, "SessionLocal", lambda: _SessionFail())

    asyncio.run(handlers.cmd_setlimit(update, context))
    assert called["db"] is False


def test_cmd_debug_denies_non_admin(monkeypatch):
    update = _Update(chat_id=999)
    context = types.SimpleNamespace(args=["status", "1"])

    monkeypatch.setattr(handlers_debug, "is_admin", lambda _cid: False)

    asyncio.run(handlers_debug.cmd_debug(update, context))

    assert update.message.sent
    assert "Acesso negado" in update.message.sent[-1]


def test_cmd_admin_health_authorized_dispatch(monkeypatch):
    update = _Update(chat_id=777)
    context = types.SimpleNamespace(args=["health", "verbose"])

    monkeypatch.setattr(handlers_admin, "is_admin", lambda _cid: True)
    called = {"ok": False, "args": None}

    async def _fake_health(_update, raw_args=None):
        called["ok"] = True
        called["args"] = raw_args

    monkeypatch.setattr(handlers_admin, "_admin_health", _fake_health)

    asyncio.run(handlers_admin.cmd_admin(update, context))
    assert called["ok"] is True
    assert called["args"] == ["verbose"]


def _mk_admin_target_user(db, chat_id=456):
    acc = Account(id=uuid.uuid4(), type="personal", name="acc", is_active=True)
    user = User(id=uuid.uuid4(), telegram_chat_id=chat_id, username=f"u{chat_id}", is_active=True, account_id=acc.id)
    db.add_all([acc, user])
    db.commit()
    return user


class _SessionWrap:
    def __init__(self, db):
        self._db = db

    def __enter__(self):
        return self._db

    def __exit__(self, *_args):
        return False


async def _allow_admin(_update):
    return True


def test_cmd_setplan_premium_uses_premium_plan_when_exists(monkeypatch, db):
    _mk_admin_target_user(db, 456)
    premium = Plan(code="premium", name="Premium", daily_alert_limit=15, max_wishlists=10, is_active=True)
    db.add(premium)
    db.commit()
    monkeypatch.setattr(handlers, "_ensure_admin", _allow_admin)
    monkeypatch.setattr(handlers, "SessionLocal", lambda: _SessionWrap(db))
    update = _Update(chat_id=123)
    context = types.SimpleNamespace(args=["premium", "456"])
    asyncio.run(handlers.cmd_setplan(update, context))
    assert "Plano atualizado para premium" in update.message.sent[-1]
    sub = db.query(Subscription).order_by(Subscription.created_at.desc()).first()
    assert sub is not None and sub.plan_id == premium.id


def test_cmd_setplan_premium_without_plan_returns_clear_error(monkeypatch, db):
    _mk_admin_target_user(db, 458)
    monkeypatch.setattr(handlers, "_ensure_admin", _allow_admin)
    monkeypatch.setattr(handlers, "SessionLocal", lambda: _SessionWrap(db))
    update = _Update(chat_id=123)
    context = types.SimpleNamespace(args=["premium", "458"])
    asyncio.run(handlers.cmd_setplan(update, context))
    assert "Plano premium não encontrado no banco" in update.message.sent[-1]


def test_cmd_setplan_free_works(monkeypatch, db):
    _mk_admin_target_user(db, 459)
    free = Plan(code="free", name="Free", daily_alert_limit=5, max_wishlists=2, is_active=True)
    db.add(free)
    db.commit()
    monkeypatch.setattr(handlers, "_ensure_admin", _allow_admin)
    monkeypatch.setattr(handlers, "SessionLocal", lambda: _SessionWrap(db))
    update = _Update(chat_id=123)
    asyncio.run(handlers.cmd_setplan(update, types.SimpleNamespace(args=["free", "459"])))
    assert "Plano atualizado para free" in update.message.sent[-1]


def test_cmd_setplan_rejects_legacy_codes(monkeypatch):
    monkeypatch.setattr(handlers, "_ensure_admin", _allow_admin)
    update = _Update(chat_id=123)
    asyncio.run(handlers.cmd_setplan(update, types.SimpleNamespace(args=["pro", "459"])))
    assert "Plano inválido. Use: free|premium" in update.message.sent[-1]
    asyncio.run(handlers.cmd_setplan(update, types.SimpleNamespace(args=["ultra", "459"])))
    assert "Plano inválido. Use: free|premium" in update.message.sent[-1]
