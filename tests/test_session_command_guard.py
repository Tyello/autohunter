from __future__ import annotations

import asyncio
import types

from app.bot import handlers_core


class _Message:
    def __init__(self):
        self.sent: list[dict] = []

    async def reply_text(self, text, reply_markup=None):
        self.sent.append({"text": text, "reply_markup": reply_markup})


class _CallbackMessage(_Message):
    pass


class _CallbackQuery:
    def __init__(self, data: str):
        self.data = data
        self.answers = 0
        self.edits: list[dict] = []
        self.message = _CallbackMessage()

    async def answer(self):
        self.answers += 1

    async def edit_message_text(self, text, reply_markup=None):
        self.edits.append({"text": text, "reply_markup": reply_markup})


class _Update:
    def __init__(self, callback_data: str | None = None):
        self.message = _Message()
        self.effective_message = self.message
        self.callback_query = _CallbackQuery(callback_data) if callback_data else None
        self.effective_chat = types.SimpleNamespace(id=123)
        self.effective_user = types.SimpleNamespace(username="tester")


def _ctx(user_data=None):
    return types.SimpleNamespace(user_data=user_data or {})


def test_guard_returns_false_without_session():
    update = _Update()
    blocked = asyncio.run(handlers_core.maybe_guard_active_session_command(update, _ctx({}), target="menu"))
    assert blocked is False
    assert update.message.sent == []


def test_guard_blocks_create_wishlist_session():
    update = _Update()
    ctx = _ctx({"menu_create_wishlist_query": "civic"})

    blocked = asyncio.run(handlers_core.maybe_guard_active_session_command(update, ctx, target="menu"))

    assert blocked is True
    payload = update.message.sent[-1]
    assert "Você tem uma ação em andamento" in payload["text"]
    callback_data = [btn.callback_data for row in payload["reply_markup"].inline_keyboard for btn in row]
    assert "SESSION:RESUME" in callback_data
    assert "SESSION:DISCARD:MENU" in callback_data


def test_guard_blocks_filter_session():
    update = _Update()
    blocked = asyncio.run(
        handlers_core.maybe_guard_active_session_command(update, _ctx({"menu_filter_wishlist_id": "w1"}), target="start")
    )
    assert blocked is True


def test_session_resume_keeps_context():
    update = _Update("SESSION:RESUME")
    ctx = _ctx({"menu_create_wishlist_query": "civic"})

    asyncio.run(handlers_core.cb_session_guard(update, ctx))

    assert "menu_create_wishlist_query" in ctx.user_data
    sent = update.callback_query.edits[-1]["text"]
    assert "continue pela última pergunta acima" in sent


def test_session_discard_menu_clears_context(monkeypatch):
    update = _Update("SESSION:DISCARD:MENU")
    ctx = _ctx(
        {
            "menu_create_wishlist_query": "civic",
            "menu_create_wishlist_draft_filters": [{"field": "price", "operator": "lte", "value": "100000"}],
            "menu_create_wishlist_include_auctions": True,
            "menu_filter_wishlist_id": "w1",
            "menu_filter_type": "price",
            "quick_search_active": True,
        }
    )

    called = {"menu": False}

    async def _show_menu(_update):
        called["menu"] = True

    monkeypatch.setattr(handlers_core, "_show_main_menu", _show_menu)

    asyncio.run(handlers_core.cb_session_guard(update, ctx))

    assert "menu_create_wishlist_query" not in ctx.user_data
    assert "menu_create_wishlist_draft_filters" not in ctx.user_data
    assert "menu_create_wishlist_include_auctions" not in ctx.user_data
    assert "menu_filter_wishlist_id" not in ctx.user_data
    assert "menu_filter_type" not in ctx.user_data
    assert "quick_search_active" not in ctx.user_data
    assert called["menu"] is True
