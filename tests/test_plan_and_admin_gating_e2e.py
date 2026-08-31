from __future__ import annotations

import asyncio
import types

from app.bot import handlers


class _Message:
    def __init__(self):
        self.sent: list[dict] = []

    async def reply_text(self, text, reply_markup=None):
        self.sent.append({"text": text, "reply_markup": reply_markup})


class _Update:
    def __init__(self, chat_id):
        self.message = _Message()
        self.effective_message = self.message
        self.callback_query = None
        self.effective_chat = types.SimpleNamespace(id=chat_id)
        self.effective_user = types.SimpleNamespace(username="tester")


class _DBSessionWrapper:
    def __init__(self, db):
        self._db = db

    def __enter__(self):
        return self._db

    def __exit__(self, *_exc):
        return None


def _ctx(args=None):
    return types.SimpleNamespace(args=args or [])


def test_cmd_setplan_blocked_for_non_admin(monkeypatch):
    monkeypatch.setattr(handlers, "is_admin", lambda _chat_id: False)
    update = _Update(chat_id=42)
    asyncio.run(handlers.cmd_setplan(update, _ctx(["premium"])))
    assert "sem permiss" in update.message.sent[-1]["text"].lower()


def test_cmd_setlimit_blocked_for_non_admin(monkeypatch):
    monkeypatch.setattr(handlers, "is_admin", lambda _chat_id: False)
    update = _Update(chat_id=42)
    asyncio.run(handlers.cmd_setlimit(update, _ctx(["10"])))
    assert "sem permiss" in update.message.sent[-1]["text"].lower()


def test_cmd_plan_renders_free_defaults_for_new_user(db, monkeypatch):
    monkeypatch.setattr(handlers, "SessionLocal", lambda: _DBSessionWrapper(db))
    update = _Update(chat_id=7001)
    asyncio.run(handlers.cmd_plan(update, _ctx()))

    text = update.message.sent[-1]["text"]
    assert "free" in text.lower()
