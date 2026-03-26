from __future__ import annotations

import asyncio
import types

from app.bot import handlers_wishlist_ui


class _Message:
    def __init__(self):
        self.sent: list[str] = []

    async def reply_text(self, text, reply_markup=None):
        self.sent.append(text)


class _Update:
    def __init__(self):
        self.effective_chat = types.SimpleNamespace(id=111)
        self.effective_user = types.SimpleNamespace(username="tester")
        self.message = _Message()
        self.effective_message = self.message


class _Session:
    def __enter__(self):
        return self

    def __exit__(self, *_):
        return None


def test_track_add_happy_path(monkeypatch):
    monkeypatch.setattr(handlers_wishlist_ui, "SessionLocal", lambda: _Session())
    monkeypatch.setattr(
        handlers_wishlist_ui,
        "get_or_create_user_by_chat",
        lambda _db, _chat_id, _username: types.SimpleNamespace(id="u1"),
    )
    monkeypatch.setattr(
        handlers_wishlist_ui,
        "add_tracked_listing",
        lambda _db, **_kwargs: (True, "Rastreamento ativado (slot 1/3)"),
    )

    update = _Update()
    context = types.SimpleNamespace(args=["1", "EXT1"])

    asyncio.run(handlers_wishlist_ui.cmd_wishlist_track_add(update, context))

    assert update.message.sent[-1].startswith("Rastreamento ativado")


def test_track_remove_requires_slot(monkeypatch):
    update = _Update()
    context = types.SimpleNamespace(args=["1"])

    asyncio.run(handlers_wishlist_ui.cmd_wishlist_track_remove(update, context))

    assert update.message.sent[-1] == "Use: /wishlist_track_remove <n> <slot>"
