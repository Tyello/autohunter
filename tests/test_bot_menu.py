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
        self.edit_payloads: list[dict] = []
        self.message = _Message()

    async def answer(self):
        self.answers += 1

    async def edit_message_text(self, text, reply_markup=None):
        if self.fail_edit:
            raise RuntimeError("cannot edit")
        self.edits.append(text)
        self.edit_payloads.append({"text": text, "reply_markup": reply_markup})


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
        "MENU:UPGRADE",
        "MENU:HELP",
    ]


def test_menu_keyboard_hides_upgrade_for_premium():
    markup = handlers_core._menu_keyboard(is_premium=True)
    callback_data = [btn.callback_data for row in markup.inline_keyboard for btn in row]
    assert "MENU:UPGRADE" not in callback_data


def test_callback_menu_search():
    q = _CallbackQuery("MENU:SEARCH")
    asyncio.run(handlers_core.cb_menu(_Update(q), types.SimpleNamespace()))
    assert q.answers == 1
    assert "/buscar civic si" in q.edits[-1]


def test_callback_menu_wishlists_real(monkeypatch):
    _patch_user(monkeypatch)
    monkeypatch.setattr(handlers_core, "get_wishlist_summaries", lambda *_: [{"index": 1, "query": "civic si", "filters_count": 0, "filters": [], "tracked_count": 0, "tracked_limit": 3, "notifications_24h_count": 2, "is_active": True}])
    q = _CallbackQuery("MENU:WISHLISTS")
    asyncio.run(handlers_core.cb_menu(_Update(q), types.SimpleNamespace()))
    assert q.answers == 1
    assert "🎯 Suas wishlists" in q.edits[-1]
    assert "1. civic si" in q.edits[-1]
    assert "Filtros:\n- Nenhum filtro" in q.edits[-1]
    assert "Rastreados: 0/3" in q.edits[-1]
    assert "Notificações: 2 nas últimas 24h" in q.edits[-1]


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


def test_callback_menu_wl_back(monkeypatch):
    _patch_user(monkeypatch)
    monkeypatch.setattr(handlers_core, "get_user_plan_snapshot", lambda *_: {"plan_code": "free"})
    q = _CallbackQuery("WL:BACK")
    asyncio.run(handlers_core.cb_menu(_Update(q), types.SimpleNamespace()))
    assert q.answers == 1
    assert "AutoHunter" in q.edits[-1]


def test_callback_menu_wl_back_keeps_upgrade_hidden_for_premium(monkeypatch):
    _patch_user(monkeypatch)
    monkeypatch.setattr(handlers_core, "get_user_plan_snapshot", lambda *_: {"plan_code": "premium"})
    q = _CallbackQuery("WL:BACK")
    asyncio.run(handlers_core.cb_menu(_Update(q), types.SimpleNamespace()))
    markup = q.edit_payloads[-1]["reply_markup"]
    callback_data = [btn.callback_data for row in markup.inline_keyboard for btn in row]
    assert "MENU:UPGRADE" not in callback_data


def test_callback_menu_wl_back_shows_upgrade_for_free(monkeypatch):
    _patch_user(monkeypatch)
    monkeypatch.setattr(handlers_core, "get_user_plan_snapshot", lambda *_: {"plan_code": "free"})
    markup = handlers_core._main_menu_markup_for_user(_Update())
    callback_data = [btn.callback_data for row in markup.inline_keyboard for btn in row]
    assert "MENU:UPGRADE" in callback_data


def test_callback_menu_wl_tracked(monkeypatch):
    _patch_user(monkeypatch)
    monkeypatch.setattr(handlers_core, "list_wishlists", lambda *_: [types.SimpleNamespace(id="w1", query="civic")])
    monkeypatch.setattr(handlers_core, "list_tracked_listings", lambda _db, **kwargs: (True, "ok"))
    q = _CallbackQuery("WL:TRACKED")
    asyncio.run(handlers_core.cb_menu(_Update(q), types.SimpleNamespace()))
    assert q.answers == 1
    assert "Seus anúncios rastreados" in q.edits[-1]


def test_callback_menu_wl_remove_flow(monkeypatch):
    _patch_user(monkeypatch)
    monkeypatch.setattr(handlers_core, "list_wishlists", lambda *_: [types.SimpleNamespace(id="w1", query="civic")])
    q = _CallbackQuery("WL:REMOVE_MENU")
    asyncio.run(handlers_core.cb_menu(_Update(q), types.SimpleNamespace()))
    assert q.answers == 1
    assert "Escolha a wishlist para remover" in q.edits[-1]

    q2 = _CallbackQuery("WL:REMOVE:1")
    asyncio.run(handlers_core.cb_menu(_Update(q2), types.SimpleNamespace()))
    assert q2.answers == 1
    assert "Remover wishlist 1" in q2.edits[-1]

    monkeypatch.setattr(handlers_core, "remove_wishlist", lambda *_args, **_kwargs: (True, "ok"))
    q3 = _CallbackQuery("WL:REMOVE_CONFIRM:1")
    asyncio.run(handlers_core.cb_menu(_Update(q3), types.SimpleNamespace()))
    assert q3.answers == 1
    assert "Wishlist removida." in q3.edits[-1]


def test_run_registers_wl_callback_pattern():
    with open("app/bot/run.py", "r", encoding="utf-8") as fh:
        content = fh.read()
    assert r'^WL:(BACK|TRACKED|REMOVE_MENU|REMOVE:\d+|REMOVE_CONFIRM:\d+)$' in content


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


def test_callback_menu_filters_legacy_redirect(monkeypatch):
    _patch_user(monkeypatch)
    q = _CallbackQuery("MENU:FILTERS")
    asyncio.run(handlers_core.cb_menu(_Update(q), types.SimpleNamespace()))
    assert q.answers == 1
    assert "filtros guiados agora" in q.edits[-1]


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
