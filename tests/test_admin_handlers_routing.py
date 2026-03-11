import types

import asyncio

from app.bot import handlers_admin


class _Msg:
    def __init__(self):
        self.sent = []

    async def reply_text(self, txt):
        self.sent.append(txt)


class _Update:
    def __init__(self):
        self.effective_chat = types.SimpleNamespace(id=1)
        self.message = _Msg()


def test_cmd_admin_sources_routing_preserved(monkeypatch):
    update = _Update()
    context = types.SimpleNamespace(args=["sources"])

    monkeypatch.setattr("app.bot.handlers_admin.is_admin", lambda _cid: True)

    called = {"ok": False}

    async def _fake_sources(update, args):
        called["ok"] = True
        assert args == []

    monkeypatch.setattr(handlers_admin, "_admin_sources_dispatch", _fake_sources)

    asyncio.run(handlers_admin.cmd_admin(update, context))
    assert called["ok"] is True
