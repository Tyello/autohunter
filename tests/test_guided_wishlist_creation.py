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
        self.edits: list[dict] = []
        self.message = _Message()

    async def answer(self):
        self.answers += 1

    async def edit_message_text(self, text, reply_markup=None):
        self.edits.append({"text": text, "reply_markup": reply_markup})


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


def test_create_flow_query_text_shows_create_options():
    msg = _Message("civic si")
    ctx = types.SimpleNamespace(user_data={})
    state = asyncio.run(handlers_core.menu_create_wishlist_on_text(_Update(message=msg), ctx))
    assert state == handlers_core.MENU_CREATE_WISHLIST_QUERY
    assert "Como deseja continuar?" in msg.sent[-1]["text"]


def test_cwl_create_calls_add_wishlist_and_ends(monkeypatch):
    _patch_user(monkeypatch)
    called = {}
    monkeypatch.setattr(handlers_core, "add_wishlist", lambda _db, _uid, q: (called.setdefault("q", q) or True, "ok"))
    ctx = types.SimpleNamespace(user_data={"menu_create_wishlist_query": "civic si"})
    q = _CallbackQuery("CWL:CREATE")
    state = asyncio.run(handlers_core.cb_menu_create_wishlist(_Update(q=q), ctx))
    assert called["q"] == "civic si"
    assert q.answers == 1
    assert state == ConversationHandler.END


def test_cwl_create_filters_enters_draft_without_creation(monkeypatch):
    _patch_user(monkeypatch)
    monkeypatch.setattr(handlers_core, "add_wishlist", lambda *_: (_ for _ in ()).throw(AssertionError("must not call")))
    monkeypatch.setattr(handlers_core, "create_wishlist_with_filters", lambda *_: (_ for _ in ()).throw(AssertionError("must not call")))
    ctx = types.SimpleNamespace(user_data={"menu_create_wishlist_query": "civic si"})
    q = _CallbackQuery("CWL:CREATE_FILTERS")
    state = asyncio.run(handlers_core.cb_menu_create_wishlist(_Update(q=q), ctx))
    assert state == handlers_core.MENU_CREATE_WISHLIST_QUERY
    assert ctx.user_data["menu_create_wishlist_draft_filters"] == []
    assert "Filtros para: civic si" in q.edits[-1]["text"]


def test_draft_filter_add_and_remove(monkeypatch):
    ctx = types.SimpleNamespace(user_data={"menu_create_wishlist_query": "civic si", "menu_create_wishlist_draft_filters": []})
    q_type = _CallbackQuery("CWLF:TYPE:state")
    asyncio.run(handlers_core.cb_menu_create_wishlist(_Update(q=q_type), ctx))
    msg = _Message("SP")
    asyncio.run(handlers_core.menu_create_wishlist_on_text(_Update(message=msg), ctx))
    assert ctx.user_data["menu_create_wishlist_draft_filters"][0]["field"] == "state"
    q_list = _CallbackQuery("CWLF:ACTION:list")
    asyncio.run(handlers_core.cb_menu_create_wishlist(_Update(q=q_list), ctx))
    q_rm = _CallbackQuery("CWLF:RM:1")
    asyncio.run(handlers_core.cb_menu_create_wishlist(_Update(q=q_rm), ctx))
    assert ctx.user_data["menu_create_wishlist_draft_filters"] == []


def test_draft_mode_free_text_does_not_override_query():
    ctx = types.SimpleNamespace(user_data={"menu_create_wishlist_query": "civic si", "menu_create_wishlist_draft_filters": []})
    msg = _Message("SP")
    state = asyncio.run(handlers_core.menu_create_wishlist_on_text(_Update(message=msg), ctx))
    assert state == handlers_core.MENU_CREATE_WISHLIST_QUERY
    assert ctx.user_data["menu_create_wishlist_query"] == "civic si"
    assert ctx.user_data["menu_create_wishlist_draft_filters"] == []
    assert "Use os botões para adicionar filtros" in msg.sent[-1]["text"]


def test_draft_done_calls_create_wishlist_with_filters(monkeypatch):
    _patch_user(monkeypatch)
    called = {}

    def _create(_db, _uid, query, filters):
        called["query"] = query
        called["filters"] = filters
        return True, "ok", "wid"

    monkeypatch.setattr(handlers_core, "create_wishlist_with_filters", _create)
    ctx = types.SimpleNamespace(user_data={
        "menu_create_wishlist_query": "civic si",
        "menu_create_wishlist_draft_filters": [{"field": "state", "operator": "eq", "value": "SP"}],
    })
    q = _CallbackQuery("CWLF:DONE")
    state = asyncio.run(handlers_core.cb_menu_create_wishlist(_Update(q=q), ctx))
    assert state == ConversationHandler.END
    assert called["query"] == "civic si"
    assert len(called["filters"]) == 1
    assert ctx.user_data == {}


def test_draft_done_without_query_expires_session():
    ctx = types.SimpleNamespace(user_data={"menu_create_wishlist_draft_filters": []})
    q = _CallbackQuery("CWLF:DONE")
    state = asyncio.run(handlers_core.cb_menu_create_wishlist(_Update(q=q), ctx))
    assert state == ConversationHandler.END
    assert ctx.user_data == {}
    assert "Sessão expirada" in q.edits[-1]["text"]


def test_draft_cancel_clears_context_and_does_not_create(monkeypatch):
    monkeypatch.setattr(handlers_core, "create_wishlist_with_filters", lambda *_: (_ for _ in ()).throw(AssertionError("must not call")))
    ctx = types.SimpleNamespace(user_data={"menu_create_wishlist_query": "civic si", "menu_create_wishlist_draft_filters": [{"field": "state", "operator": "eq", "value": "SP"}]})
    q = _CallbackQuery("CWLF:CANCEL")
    state = asyncio.run(handlers_core.cb_menu_create_wishlist(_Update(q=q), ctx))
    assert state == ConversationHandler.END
    assert ctx.user_data == {}
    assert "cancelada" in q.edits[-1]["text"]
