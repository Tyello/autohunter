import asyncio
import types

from telegram.ext import ConversationHandler

from app.bot import handlers


class _CallbackMessage:
    def __init__(self):
        self.sent = []

    async def reply_text(self, text):
        self.sent.append(text)


class _CallbackQuery:
    def __init__(self, data="MENU:SEARCH"):
        self.data = data
        self.answers = 0
        self.message = _CallbackMessage()

    async def answer(self):
        self.answers += 1


class _Message:
    def __init__(self, text=""):
        self.text = text
        self.sent = []

    async def reply_text(self, text):
        self.sent.append(text)


def test_menu_search_starts_conversation():
    q = _CallbackQuery()
    upd = types.SimpleNamespace(callback_query=q)
    ctx = types.SimpleNamespace(user_data={})
    state = asyncio.run(handlers.cb_quick_search_start(upd, ctx))
    assert state == handlers.QUICK_SEARCH_QUERY
    assert q.answers == 1
    assert ctx.user_data["quick_search_active"] is True
    assert "O que você procura?" in q.message.sent[-1]
    assert "civic si" in q.message.sent[-1]


def test_quick_search_on_text_runs_manual_search_and_ends(monkeypatch):
    called = {}

    async def _start(update, context, *, query, sources=None):
        called["query"] = query
        called["sources"] = sources

    monkeypatch.setattr(handlers, "start_manual_search_flow", _start)
    upd = types.SimpleNamespace(message=_Message("golf gti manual sp"))
    ctx = types.SimpleNamespace(user_data={"quick_search_active": True})
    state = asyncio.run(handlers.quick_search_on_text(upd, ctx))
    assert called == {"query": "golf gti manual sp", "sources": None}
    assert "quick_search_active" not in ctx.user_data
    assert state == ConversationHandler.END


def test_quick_search_on_empty_text_keeps_state(monkeypatch):
    sent = []

    async def _reply(*_args, **_kwargs):
        sent.append(_args[1])

    monkeypatch.setattr(handlers, "reply_text", _reply)
    upd = types.SimpleNamespace(message=_Message("   "))
    state = asyncio.run(handlers.quick_search_on_text(upd, types.SimpleNamespace()))
    assert "Me diga o que você quer buscar" in sent[-1]
    assert state == handlers.QUICK_SEARCH_QUERY


def test_quick_search_cancel(monkeypatch):
    sent = []

    async def _reply(*_args, **_kwargs):
        sent.append(_args[1])

    monkeypatch.setattr(handlers, "reply_text", _reply)
    ctx = types.SimpleNamespace(user_data={"quick_search_active": True})
    state = asyncio.run(handlers.quick_search_cancel(types.SimpleNamespace(), ctx))
    assert "Busca rápida cancelada" in sent[-1]
    assert "quick_search_active" not in ctx.user_data
    assert state == ConversationHandler.END
