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
    state = asyncio.run(handlers_core.cb_menu(_Update(q=q), types.SimpleNamespace(user_data={})))
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
    ctx = types.SimpleNamespace(user_data={})
    state = asyncio.run(handlers_core.menu_create_wishlist_on_text(_Update(message=msg), ctx))
    assert state == handlers_core.MENU_CREATE_WISHLIST_CONFIRM
    assert created == {}
    assert "Como deseja continuar?" in msg.sent[-1]["text"]
    assert ctx.user_data["menu_create_wishlist_query"] == "civic si"


def test_menu_create_wishlist_service_error_keeps_flow_and_shows_service_message(monkeypatch):
    _patch_user(monkeypatch)

    def _add(_db, _uid, _query):
        return False, "Limite atingido: 3 wishlists no seu plano."

    monkeypatch.setattr(handlers_core, "add_wishlist", _add)
    msg = _Message("civic si")
    state = asyncio.run(handlers_core.menu_create_wishlist_on_text(_Update(message=msg), types.SimpleNamespace(user_data={})))

    assert state == handlers_core.MENU_CREATE_WISHLIST_CONFIRM
    assert "Como deseja continuar?" in msg.sent[-1]["text"]


def test_menu_create_wishlist_retry_after_error_then_success(monkeypatch):
    _patch_user(monkeypatch)
    calls = {"n": 0}

    def _add(_db, _uid, query):
        calls["n"] += 1
        if calls["n"] == 1:
            return False, "Query inválida. Ex: /wishlist_add audi a6 entre 2014 e 2020"
        return True, "Wishlist criada."

    monkeypatch.setattr(handlers_core, "add_wishlist", _add)

    ctx = types.SimpleNamespace(user_data={})
    msg = _Message("x")
    state = asyncio.run(handlers_core.menu_create_wishlist_on_text(_Update(message=msg), ctx))
    assert state == handlers_core.MENU_CREATE_WISHLIST_CONFIRM


def test_menu_create_wishlist_empty_text_does_not_create(monkeypatch):
    _patch_user(monkeypatch)
    called = {"n": 0}

    def _add(*_args, **_kwargs):
        called["n"] += 1
        return True, "ok"

    monkeypatch.setattr(handlers_core, "add_wishlist", _add)
    msg = _Message("   ")
    state = asyncio.run(handlers_core.menu_create_wishlist_on_text(_Update(message=msg), types.SimpleNamespace(user_data={})))
    assert state == handlers_core.MENU_CREATE_WISHLIST_QUERY
    assert called["n"] == 0
    assert "Texto inválido" in msg.sent[-1]["text"]


def test_menu_create_wishlist_cancel():
    msg = _Message()
    state = asyncio.run(handlers_core.menu_create_wishlist_cancel(_Update(message=msg), types.SimpleNamespace(user_data={})))
    assert state == ConversationHandler.END
    assert "cancelada" in msg.sent[-1]["text"]


def test_menu_create_wishlist_multiple_sequential(monkeypatch):
    _patch_user(monkeypatch)
    created: list[str] = []
    monkeypatch.setattr(handlers_core, "add_wishlist", lambda _db, _uid, q: (created.append(q) or True, "ok"))

    msg1 = _Message("miata")
    msg2 = _Message("corolla 2018")
    asyncio.run(handlers_core.menu_create_wishlist_on_text(_Update(message=msg1), types.SimpleNamespace(user_data={})))
    asyncio.run(handlers_core.menu_create_wishlist_on_text(_Update(message=msg2), types.SimpleNamespace(user_data={})))

    assert created == []


def test_menu_create_wishlist_confirm_create(monkeypatch):
    _patch_user(monkeypatch)
    monkeypatch.setattr(handlers_core, "add_wishlist", lambda *_: (True, "Wishlist criada: civic si"))
    monkeypatch.setattr(handlers_core, "list_wishlists", lambda *_: [types.SimpleNamespace(id="wl-1", query="civic si")])
    q = _CallbackQuery("CWL:CREATE")
    ctx = types.SimpleNamespace(user_data={"menu_create_wishlist_query": "civic si"})
    state = asyncio.run(handlers_core.cb_menu_create_wishlist_confirm(_Update(q=q), ctx))
    assert state == ConversationHandler.END
    assert q.answers == 1
    assert "Use /menu para ver suas buscas" in q.edits[-1]


def test_menu_create_wishlist_create_filters_routes_to_filter_callbacks(monkeypatch):
    _patch_user(monkeypatch)
    monkeypatch.setattr(handlers_core, "add_wishlist", lambda *_: (True, "Wishlist criada: civic si"))
    monkeypatch.setattr(handlers_core, "list_wishlists", lambda *_: [types.SimpleNamespace(id="wl-1", query="civic si")])
    ctx = types.SimpleNamespace(user_data={"menu_create_wishlist_query": "civic si"})

    q_create = _CallbackQuery("CWL:CREATE_FILTERS")
    state_create = asyncio.run(handlers_core.cb_menu_create_wishlist_confirm(_Update(q=q_create), ctx))
    assert state_create == handlers_core.MENU_FILTER_SELECT_VALUE
    assert q_create.answers == 1
    assert "Agora vamos melhorar essa busca com filtros." in q_create.edits[-1]

    q_add = _CallbackQuery("FILTER:ACTION:add")
    state_add = asyncio.run(handlers_core.cb_menu_filter(_Update(q=q_add), ctx))
    assert state_add == handlers_core.MENU_FILTER_SELECT_VALUE
    assert q_add.answers == 1
    assert "Escolha o tipo de filtro:" in q_add.edits[-1]

    q_done = _CallbackQuery("FILTER:DONE")
    state_done = asyncio.run(handlers_core.cb_menu_filter(_Update(q=q_done), ctx))
    assert state_done == ConversationHandler.END
    assert q_done.answers == 1
    assert "Tudo certo. Use /menu para acompanhar suas buscas." in q_done.edits[-1]


def test_menu_create_wishlist_create_filters_cancel(monkeypatch):
    _patch_user(monkeypatch)
    monkeypatch.setattr(handlers_core, "add_wishlist", lambda *_: (True, "Wishlist criada: civic si"))
    monkeypatch.setattr(handlers_core, "list_wishlists", lambda *_: [types.SimpleNamespace(id="wl-1", query="civic si")])
    ctx = types.SimpleNamespace(user_data={"menu_create_wishlist_query": "civic si"})

    q_create = _CallbackQuery("CWL:CREATE_FILTERS")
    asyncio.run(handlers_core.cb_menu_create_wishlist_confirm(_Update(q=q_create), ctx))
    q_cancel = _CallbackQuery("FILTER:CANCEL")
    state_cancel = asyncio.run(handlers_core.cb_menu_filter(_Update(q=q_cancel), ctx))
    assert state_cancel == ConversationHandler.END
    assert q_cancel.answers == 1
    assert "Configuração de filtro cancelada." in q_cancel.edits[-1]


def test_menu_create_wishlist_conversation_has_filter_state():
    conv = handlers_core.menu_create_wishlist_conversation()
    assert handlers_core.MENU_FILTER_SELECT_VALUE in conv.states
