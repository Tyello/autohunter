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
        self.answers = 0
        self.edits: list[str] = []
        self.message = _Message()

    async def answer(self):
        self.answers += 1

    async def edit_message_text(self, text, reply_markup=None):
        self.edits.append(text)


class _Update:
    def __init__(self, message: _Message | None = None, q: _CallbackQuery | None = None):
        self.message = message
        self.effective_message = message or _Message()
        self.callback_query = q
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


def test_menu_create_wishlist_starts_flow():
    q = _CallbackQuery("MENU:CREATE_WISHLIST")
    state = asyncio.run(handlers_core.cb_menu(_Update(q=q), types.SimpleNamespace()))
    assert state == handlers_core.MENU_CREATE_WISHLIST_QUERY
    assert "Qual carro você quer monitorar?" in q.edits[-1]


def test_menu_create_wishlist_creates_on_text(monkeypatch):
    _patch_user(monkeypatch)
    created = {}

    def _add(_db, user_id, query):
        created["user_id"] = user_id
        created["query"] = query
        return True, "ok"

    monkeypatch.setattr(handlers_core, "add_wishlist", _add)
    msg = _Message("civic si")
    state = asyncio.run(handlers_core.menu_create_wishlist_on_text(_Update(message=msg), types.SimpleNamespace()))

    assert state == ConversationHandler.END
    assert created["query"] == "civic si"
    assert "✅ Wishlist criada: civic si" in msg.sent[-1]["text"]
    assert "Para filtros: /menu → ⚙️ Filtros" in msg.sent[-1]["text"]


def test_menu_create_wishlist_service_error_keeps_flow_and_shows_service_message(monkeypatch):
    _patch_user(monkeypatch)

    def _add(_db, _uid, _query):
        return False, "Limite atingido: 3 wishlists no seu plano."

    monkeypatch.setattr(handlers_core, "add_wishlist", _add)
    msg = _Message("civic si")
    state = asyncio.run(handlers_core.menu_create_wishlist_on_text(_Update(message=msg), types.SimpleNamespace()))

    assert state == handlers_core.MENU_CREATE_WISHLIST_QUERY
    assert "✅ Wishlist criada" not in msg.sent[-1]["text"]
    assert "Não consegui criar a wishlist:" in msg.sent[-1]["text"]
    assert "Limite atingido: 3 wishlists no seu plano." in msg.sent[-1]["text"]
    assert "Envie outro texto ou use /cancelar." in msg.sent[-1]["text"]


def test_menu_create_wishlist_retry_after_error_then_success(monkeypatch):
    _patch_user(monkeypatch)
    calls = {"n": 0}

    def _add(_db, _uid, query):
        calls["n"] += 1
        if calls["n"] == 1:
            return False, "Query inválida. Ex: /wishlist_add audi a6 entre 2014 e 2020"
        return True, "Wishlist criada."

    monkeypatch.setattr(handlers_core, "add_wishlist", _add)

    msg_err = _Message("x")
    state_err = asyncio.run(handlers_core.menu_create_wishlist_on_text(_Update(message=msg_err), types.SimpleNamespace()))
    assert state_err == handlers_core.MENU_CREATE_WISHLIST_QUERY
    assert "Não consegui criar a wishlist:" in msg_err.sent[-1]["text"]

    msg_ok = _Message("civic si")
    state_ok = asyncio.run(handlers_core.menu_create_wishlist_on_text(_Update(message=msg_ok), types.SimpleNamespace()))
    assert state_ok == ConversationHandler.END
    assert "✅ Wishlist criada: civic si" in msg_ok.sent[-1]["text"]


def test_menu_create_wishlist_empty_text_does_not_create(monkeypatch):
    _patch_user(monkeypatch)
    called = {"n": 0}

    def _add(*_args, **_kwargs):
        called["n"] += 1
        return True, "ok"

    monkeypatch.setattr(handlers_core, "add_wishlist", _add)
    msg = _Message("   ")
    state = asyncio.run(handlers_core.menu_create_wishlist_on_text(_Update(message=msg), types.SimpleNamespace()))
    assert state == handlers_core.MENU_CREATE_WISHLIST_QUERY
    assert called["n"] == 0
    assert "Texto inválido" in msg.sent[-1]["text"]


def test_menu_create_wishlist_cancel():
    msg = _Message()
    state = asyncio.run(handlers_core.menu_create_wishlist_cancel(_Update(message=msg), types.SimpleNamespace()))
    assert state == ConversationHandler.END
    assert "cancelada" in msg.sent[-1]["text"]


def test_menu_create_wishlist_multiple_sequential(monkeypatch):
    _patch_user(monkeypatch)
    created: list[str] = []
    monkeypatch.setattr(handlers_core, "add_wishlist", lambda _db, _uid, q: (created.append(q) or True, "ok"))

    msg1 = _Message("miata")
    msg2 = _Message("corolla 2018")
    asyncio.run(handlers_core.menu_create_wishlist_on_text(_Update(message=msg1), types.SimpleNamespace()))
    asyncio.run(handlers_core.menu_create_wishlist_on_text(_Update(message=msg2), types.SimpleNamespace()))

    assert created == ["miata", "corolla 2018"]
