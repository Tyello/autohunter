from __future__ import annotations

import asyncio
import types

from app.bot import handlers_core
from app.bot.commands import ADVANCED_USER_COMMANDS, COMMANDS


class _Message:
    def __init__(self):
        self.sent: list[dict] = []

    async def reply_text(self, text, reply_markup=None):
        self.sent.append({"text": text, "reply_markup": reply_markup})


class _CallbackQuery:
    def __init__(self, data: str, fail_edit: bool = False):
        self.data = data
        self.fail_edit = fail_edit
        self.answers = 0
        self.edits: list[str] = []
        self.message = _Message()

    async def answer(self):
        self.answers += 1

    async def edit_message_text(self, text, reply_markup=None):
        if self.fail_edit:
            raise RuntimeError("cannot edit")
        self.edits.append(text)


class _Update:
    def __init__(self, q: _CallbackQuery | None = None):
        self.message = _Message()
        self.effective_message = self.message
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


def test_cmd_menu_renders_buttons():
    update = _Update()
    asyncio.run(handlers_core.cmd_menu(update, types.SimpleNamespace()))

    payload = update.message.sent[-1]
    assert "AutoHunter" in payload["text"]
    markup = payload["reply_markup"]
    callback_data = [btn.callback_data for row in markup.inline_keyboard for btn in row]
    assert callback_data == [
        "MENU:CREATE_WISHLIST",
        "MENU:WISHLISTS",
        "MENU:TRACKED",
        "MENU:SEARCH",
        "MENU:FILTERS",
        "MENU:HELP",
    ]


def test_callback_menu_search():
    q = _CallbackQuery("MENU:SEARCH")
    asyncio.run(handlers_core.cb_menu(_Update(q), types.SimpleNamespace()))
    assert q.answers == 1
    assert "/buscar civic si" in q.edits[-1]


def test_callback_menu_wishlists_real(monkeypatch):
    _patch_user(monkeypatch)
    monkeypatch.setattr(handlers_core, "get_wishlist_summaries", lambda *_: [{"index": 1, "query": "civic si", "filters_count": 0, "tracked_count": 0, "tracked_limit": 3, "is_active": True}])
    q = _CallbackQuery("MENU:WISHLISTS")
    asyncio.run(handlers_core.cb_menu(_Update(q), types.SimpleNamespace()))
    assert q.answers == 1
    assert "🎯 Suas wishlists" in q.edits[-1]
    assert "1. civic si" in q.edits[-1]
    assert "Filtros: 0" in q.edits[-1]
    assert "Rastreados: 0/3" in q.edits[-1]


def test_callback_menu_wishlists_empty_guides_create(monkeypatch):
    _patch_user(monkeypatch)
    monkeypatch.setattr(handlers_core, "get_wishlist_summaries", lambda *_: [])
    q = _CallbackQuery("MENU:WISHLISTS")
    asyncio.run(handlers_core.cb_menu(_Update(q), types.SimpleNamespace()))
    assert q.answers == 1
    assert "/wishlist_add" in q.edits[-1]


def test_callback_menu_tracked_real(monkeypatch):
    _patch_user(monkeypatch)
    monkeypatch.setattr(handlers_core, "list_wishlists", lambda *_: [types.SimpleNamespace(id="w1", query="civic")])
    monkeypatch.setattr(handlers_core, "list_tracked_listings", lambda _db, **kwargs: (True, f"📌 Rastreados da wishlist {kwargs['wishlist_index']}"))
    q = _CallbackQuery("MENU:TRACKED")
    asyncio.run(handlers_core.cb_menu(_Update(q), types.SimpleNamespace()))
    assert q.answers == 1
    assert "Seus anúncios rastreados" in q.edits[-1]
    assert "wishlist 1" in q.edits[-1]


def test_callback_menu_tracked_empty_slots(monkeypatch):
    _patch_user(monkeypatch)
    monkeypatch.setattr(handlers_core, "list_wishlists", lambda *_: [types.SimpleNamespace(id="w1", query="civic")])
    monkeypatch.setattr(
        handlers_core,
        "list_tracked_listings",
        lambda _db, **kwargs: (True, "📌 Rastreados da wishlist 1 — civic\n1) (vazio)\n2) (vazio)\n3) (vazio)"),
    )
    q = _CallbackQuery("MENU:TRACKED")
    asyncio.run(handlers_core.cb_menu(_Update(q), types.SimpleNamespace()))
    assert q.answers == 1
    assert "(vazio)" in q.edits[-1]


def test_callback_menu_filters(monkeypatch):
    _patch_user(monkeypatch)
    monkeypatch.setattr(handlers_core, "list_wishlists", lambda *_: [types.SimpleNamespace(id="wl1", query="civic si")])
    q = _CallbackQuery("MENU:FILTERS")
    asyncio.run(handlers_core.cb_menu(_Update(q), types.SimpleNamespace()))
    assert q.answers == 1
    assert "Escolha a wishlist" in q.edits[-1]


def test_callback_menu_help_real():
    q = _CallbackQuery("MENU:HELP")
    asyncio.run(handlers_core.cb_menu(_Update(q), types.SimpleNamespace()))
    assert q.answers == 1
    assert "Comandos do AutoHunter" in q.edits[-1]
    assert "/menu" in q.edits[-1]


def test_callback_menu_invalid_does_not_break():
    q = _CallbackQuery("MENU:UNKNOWN")
    asyncio.run(handlers_core.cb_menu(_Update(q), types.SimpleNamespace()))
    assert q.answers == 1
    assert "inválida" in q.edits[-1]


def test_callback_menu_fallback_when_edit_fails():
    q = _CallbackQuery("MENU:SEARCH", fail_edit=True)
    asyncio.run(handlers_core.cb_menu(_Update(q), types.SimpleNamespace()))
    assert q.answers == 1
    assert "/buscar civic si" in q.message.sent[-1]["text"]


def test_quick_commands_still_registered():
    names = {c.command for c in ADVANCED_USER_COMMANDS}
    assert "buscar" in names
    assert "wishlist" in names
