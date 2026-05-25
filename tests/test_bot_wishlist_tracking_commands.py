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
        "add_tracked_listing_result",
        lambda _db, **_kwargs: handlers_wishlist_ui.TrackedListingResult(ok=True, status="added", message="Rastreamento ativado (slot 1/3)"),
    )

    update = _Update()
    context = types.SimpleNamespace(args=["1", "EXT1"])

    asyncio.run(handlers_wishlist_ui.cmd_wishlist_track_add(update, context))

    assert update.message.sent[-1].startswith("Rastreamento ativado")


def test_track_remove_requires_slot(monkeypatch):
    update = _Update()
    context = types.SimpleNamespace(args=["1"])

    asyncio.run(handlers_wishlist_ui.cmd_wishlist_track_remove(update, context))

    assert update.message.sent[-1] == "Use: /wishlist_track_remove <n> <slot ou id do anúncio>"


def test_track_remove_accepts_listing_id(monkeypatch):
    monkeypatch.setattr(handlers_wishlist_ui, "SessionLocal", lambda: _Session())
    monkeypatch.setattr(handlers_wishlist_ui, "get_or_create_user_by_chat", lambda *_: types.SimpleNamespace(id="u1"))
    monkeypatch.setattr(handlers_wishlist_ui, "remove_tracked_listing", lambda _db, **kwargs: (True, f"ok:{kwargs.get('car_listing_id')}"))
    update = _Update()
    context = types.SimpleNamespace(args=["1", "123e4567-e89b-12d3-a456-426614174000"])
    asyncio.run(handlers_wishlist_ui.cmd_wishlist_track_remove(update, context))
    assert update.message.sent[-1].startswith("ok:123e4567")


def test_track_alert_on_free_blocked(monkeypatch):
    monkeypatch.setattr(handlers_wishlist_ui, "SessionLocal", lambda: _Session())
    monkeypatch.setattr(handlers_wishlist_ui, "get_or_create_user_by_chat", lambda *_: types.SimpleNamespace(id="u1"))
    monkeypatch.setattr(handlers_wishlist_ui, "user_has_tracking_automation", lambda *_args, **_kwargs: False)
    update = _Update()
    context = types.SimpleNamespace(args=["1", "1"])
    asyncio.run(handlers_wishlist_ui.cmd_wishlist_track_alert_on(update, context))
    assert "Premium" in update.message.sent[-1]


def test_track_alert_on_premium_ok(monkeypatch):
    monkeypatch.setattr(handlers_wishlist_ui, "SessionLocal", lambda: _Session())
    monkeypatch.setattr(handlers_wishlist_ui, "get_or_create_user_by_chat", lambda *_: types.SimpleNamespace(id="u1"))
    monkeypatch.setattr(handlers_wishlist_ui, "user_has_tracking_automation", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(handlers_wishlist_ui, "set_price_drop_alert_enabled", lambda *_args, **_kwargs: (True, "ok"))
    update = _Update()
    context = types.SimpleNamespace(args=["1", "1"])
    asyncio.run(handlers_wishlist_ui.cmd_wishlist_track_alert_on(update, context))
    assert update.message.sent[-1] == "ok"


def test_track_list_without_args_lists_all(monkeypatch):
    monkeypatch.setattr(handlers_wishlist_ui, "SessionLocal", lambda: _Session())
    monkeypatch.setattr(handlers_wishlist_ui, "get_or_create_user_by_chat", lambda *_: types.SimpleNamespace(id="u1"))
    monkeypatch.setattr(handlers_wishlist_ui, "list_wishlists", lambda *_: [types.SimpleNamespace(id="w1"), types.SimpleNamespace(id="w2")])
    monkeypatch.setattr(handlers_wishlist_ui, "list_tracked_listings", lambda _db, **kwargs: (True, f"📌 Rastreados da wishlist {kwargs['wishlist_index']} — q"))
    update = _Update()
    asyncio.run(handlers_wishlist_ui.cmd_wishlist_track_list(update, types.SimpleNamespace(args=[])))
    assert "⭐ Anúncios rastreados" in update.message.sent[-1]
