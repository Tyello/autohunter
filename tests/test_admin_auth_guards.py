import asyncio
import types

from app.bot import handlers
from app.bot import handlers_admin
from app.bot import handlers_debug


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
    context = types.SimpleNamespace(args=["pro", "456"])

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
