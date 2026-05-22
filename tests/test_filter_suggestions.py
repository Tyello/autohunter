from __future__ import annotations

import asyncio
import types

from telegram.ext import ConversationHandler

from app.bot import handlers_core


class _Message:
    def __init__(self, text: str = ""):
        self.text = text
        self.sent: list[dict] = []

    async def reply_text(self, text, reply_markup=None):
        self.sent.append({"text": text, "reply_markup": reply_markup})


class _CallbackQuery:
    def __init__(self, data: str):
        self.data = data
        self.edits: list[dict] = []
        self.answers = 0
        self.message = _Message()

    async def answer(self):
        self.answers += 1

    async def edit_message_text(self, text, reply_markup=None):
        self.edits.append({"text": text, "reply_markup": reply_markup})


class _Update:
    def __init__(self, q: _CallbackQuery | None = None, message: _Message | None = None):
        self.callback_query = q
        self.message = message
        self.effective_message = message
        self.effective_chat = types.SimpleNamespace(id=123)
        self.effective_user = types.SimpleNamespace(username="tester")


class _Session:
    def __enter__(self):
        return self

    def __exit__(self, *_):
        return None


def _patch_user(monkeypatch):
    monkeypatch.setattr(handlers_core, "SessionLocal", lambda: _Session())
    monkeypatch.setattr(handlers_core, "get_or_create_user_by_chat", lambda *_: types.SimpleNamespace(id="u1"))


def test_draft_price_type_shows_suggestions():
    ctx = types.SimpleNamespace(user_data={})
    q = _CallbackQuery("CWLF:TYPE:price")
    state = asyncio.run(handlers_core.cb_menu_create_wishlist(_Update(q=q), ctx))
    assert state == handlers_core.MENU_CREATE_WISHLIST_QUERY
    payload = q.edits[-1]
    assert "Qual faixa de preço" in payload["text"]
    texts = [b.text for row in payload["reply_markup"].inline_keyboard for b in row]
    assert "até R$ 80.000" in texts
    assert "✍️ Digitar outro valor" in texts


def test_draft_price_suggestion_applies_filter():
    ctx = types.SimpleNamespace(user_data={"menu_create_wishlist_query": "civic", "menu_create_wishlist_draft_filters": [], "menu_create_wishlist_draft_filter_type": "price"})
    q = _CallbackQuery("CWLF:SUG:price:0")
    state = asyncio.run(handlers_core.cb_menu_create_wishlist(_Update(q=q), ctx))
    assert state == handlers_core.MENU_CREATE_WISHLIST_QUERY
    groups = ctx.user_data["menu_create_wishlist_draft_filters"]
    assert len(groups) == 1
    assert groups[0]["group"] == "price"
    assert "Preço até" in groups[0]["label"]
    assert "Filtro adicionado/atualizado" in q.edits[-1]["text"]


def test_filter_type_mileage_shows_suggestions():
    ctx = types.SimpleNamespace(user_data={"menu_filter_wishlist_id": "w1"})
    q = _CallbackQuery("FILTER:TYPE:mileage")
    state = asyncio.run(handlers_core.cb_menu_filter(_Update(q=q), ctx))
    assert state == handlers_core.MENU_FILTER_SELECT_VALUE
    payload = q.edits[-1]
    assert "Qual quilometragem" in payload["text"]
    texts = [b.text for row in payload["reply_markup"].inline_keyboard for b in row]
    assert "até 80.000 km" in texts


def test_filter_suggestion_manual_keeps_waiting_for_text():
    ctx = types.SimpleNamespace(user_data={"menu_filter_wishlist_id": "w1", "menu_filter_type": "price"})
    q = _CallbackQuery("FILTER:SUG:price:manual")
    state = asyncio.run(handlers_core.cb_menu_filter(_Update(q=q), ctx))
    assert state == handlers_core.MENU_FILTER_SELECT_VALUE
    assert "Digite o valor desejado" in q.edits[-1]["text"]


def test_filter_suggestion_applies_parser_and_replaces(monkeypatch):
    _patch_user(monkeypatch)
    ctx = types.SimpleNamespace(user_data={"menu_filter_wishlist_id": "w1", "menu_filter_type": "price"})
    monkeypatch.setattr(handlers_core, "list_wishlists", lambda *_: [types.SimpleNamespace(id="w1", query="civic")])
    monkeypatch.setattr(handlers_core, "list_filters", lambda *_: [types.SimpleNamespace(field="price", operator="lte", value="99000")])
    removed = []
    monkeypatch.setattr(handlers_core, "remove_filter", lambda *_args: removed.append(_args) or (True, "ok"))
    calls = []
    monkeypatch.setattr(handlers_core, "add_filter", lambda _db, _wid, f, op, v: calls.append((f, op, v)) or (True, "ok"))

    q = _CallbackQuery("FILTER:SUG:price:0")
    state = asyncio.run(handlers_core.cb_menu_filter(_Update(q=q), ctx))
    assert state == handlers_core.MENU_FILTER_SELECT_VALUE
    assert removed
    assert calls[0][0] == "price"
    assert calls[0][1] == "lte"
    assert calls[0][2] == "80000"
    assert "Filtro atualizado" in q.edits[-1]["text"]


def test_manual_draft_text_still_works():
    ctx = types.SimpleNamespace(user_data={"menu_create_wishlist_query": "civic", "menu_create_wishlist_draft_filters": [], "menu_create_wishlist_draft_filter_type": "price"})
    msg = _Message("até 120000")
    state = asyncio.run(handlers_core.menu_create_wishlist_on_text(_Update(message=msg), ctx))
    assert state == handlers_core.MENU_CREATE_WISHLIST_QUERY
    assert ctx.user_data["menu_create_wishlist_draft_filters"][0]["group"] == "price"


def test_manual_filter_text_still_works(monkeypatch):
    _patch_user(monkeypatch)
    ctx = types.SimpleNamespace(user_data={"menu_filter_wishlist_id": "w1", "menu_filter_type": "year"})
    monkeypatch.setattr(handlers_core, "list_wishlists", lambda *_: [types.SimpleNamespace(id="w1", query="civic")])
    monkeypatch.setattr(handlers_core, "list_filters", lambda *_: [])
    monkeypatch.setattr(handlers_core, "add_filter", lambda *_: (True, "ok"))

    msg = _Message("a partir de 2018")
    state = asyncio.run(handlers_core.menu_filter_on_value(_Update(message=msg), ctx))
    assert state == handlers_core.MENU_FILTER_SELECT_VALUE
