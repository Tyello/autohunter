from __future__ import annotations

import asyncio
import types
import uuid

from app.bot import handlers_debug
from app.models.user import User
from app.models.wishlist import Wishlist


class _Message:
    def __init__(self):
        self.sent: list[dict] = []

    async def reply_text(self, text, disable_web_page_preview=None):
        self.sent.append({"text": text})


class _Update:
    def __init__(self, chat_id, username="tester"):
        self.message = _Message()
        self.effective_message = self.message
        self.effective_chat = types.SimpleNamespace(id=chat_id)
        self.effective_user = types.SimpleNamespace(username=username)


class _DBSessionWrapper:
    def __init__(self, db):
        self._db = db

    def __enter__(self):
        return self._db

    def __exit__(self, *_exc):
        return None


def _ctx(args=None):
    return types.SimpleNamespace(args=args or [])


def _use_real_db(monkeypatch, db):
    monkeypatch.setattr(handlers_debug, "SessionLocal", lambda: _DBSessionWrapper(db))


def _make_user(db, chat_id):
    user = User(id=uuid.uuid4(), telegram_chat_id=chat_id, username="tester", is_active=True)
    db.add(user)
    db.commit()
    return user


def _make_wishlist(db, user_id, query="civic si"):
    wishlist = Wishlist(id=uuid.uuid4(), user_id=user_id, query=query, is_active=True)
    db.add(wishlist)
    db.commit()
    return wishlist


def test_cmd_debug_blocked_for_non_admin(monkeypatch):
    monkeypatch.setattr(handlers_debug, "is_admin", lambda _chat_id: False)
    update = _Update(chat_id=42)
    asyncio.run(handlers_debug.cmd_debug(update, _ctx(["status", "1"])))
    assert "acesso negado" in update.message.sent[-1]["text"].lower()


def test_cmd_debug_no_args_shows_usage(monkeypatch):
    monkeypatch.setattr(handlers_debug, "is_admin", lambda _chat_id: True)
    update = _Update(chat_id=42)
    asyncio.run(handlers_debug.cmd_debug(update, _ctx([])))
    assert "/debug run" in update.message.sent[-1]["text"]


def test_cmd_debug_missing_index_shows_usage(monkeypatch):
    monkeypatch.setattr(handlers_debug, "is_admin", lambda _chat_id: True)
    update = _Update(chat_id=42)
    asyncio.run(handlers_debug.cmd_debug(update, _ctx(["status"])))
    assert "/debug run" in update.message.sent[-1]["text"]


def test_cmd_debug_status_invalid_wishlist_index(db, monkeypatch):
    _use_real_db(monkeypatch, db)
    monkeypatch.setattr(handlers_debug, "is_admin", lambda _chat_id: True)
    chat_id = 8001
    _make_user(db, chat_id)

    update = _Update(chat_id)
    asyncio.run(handlers_debug.cmd_debug(update, _ctx(["status", "1"])))
    assert "wishlist inválida" in update.message.sent[-1]["text"].lower()


def test_cmd_debug_status_happy_path(db, monkeypatch):
    _use_real_db(monkeypatch, db)
    monkeypatch.setattr(handlers_debug, "is_admin", lambda _chat_id: True)
    chat_id = 8002
    user = _make_user(db, chat_id)
    _make_wishlist(db, user.id, query="civic si turbo")

    update = _Update(chat_id)
    asyncio.run(handlers_debug.cmd_debug(update, _ctx(["status", "1"])))

    text = update.message.sent[-1]["text"]
    assert "civic si turbo" in text
    assert "sem duplicados" in text.lower()


def test_cmd_debug_invalid_action_word(db, monkeypatch):
    _use_real_db(monkeypatch, db)
    monkeypatch.setattr(handlers_debug, "is_admin", lambda _chat_id: True)
    chat_id = 8003
    user = _make_user(db, chat_id)
    _make_wishlist(db, user.id)

    update = _Update(chat_id)
    asyncio.run(handlers_debug.cmd_debug(update, _ctx(["bogus", "1"])))
    assert "inválida" in update.message.sent[-1]["text"].lower()
