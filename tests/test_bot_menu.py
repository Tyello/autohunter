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
    assert "Buscar agora" in q.edits[-1]
    assert "/buscar civic 2019 até 90000 sp" in q.edits[-1]


def test_callback_menu_wishlists_real(monkeypatch):
    _patch_user(monkeypatch)
    monkeypatch.setattr(handlers_core, "get_wishlist_summaries", lambda *_: [{"index": 1, "query": "civic si", "filters_count": 0, "filters": [], "tracked_count": 0, "tracked_limit": 3, "notifications_24h_count": 2, "is_active": True}])
    q = _CallbackQuery("MENU:WISHLISTS")
    asyncio.run(handlers_core.cb_menu(_Update(q), types.SimpleNamespace()))
    assert q.answers == 1
    assert "🎯 Minhas buscas" in q.edits[-1]
    assert "1. civic si" in q.edits[-1]
    assert "Filtros:\n- Nenhum filtro" in q.edits[-1]
    assert "Anúncios rastreados: 0/3" in q.edits[-1]
    assert "Alertas enviados hoje: 2" in q.edits[-1]


def test_callback_menu_wishlists_empty_guides_create(monkeypatch):
    _patch_user(monkeypatch)
    monkeypatch.setattr(handlers_core, "get_wishlist_summaries", lambda *_: [])
    q = _CallbackQuery("MENU:WISHLISTS")
    asyncio.run(handlers_core.cb_menu(_Update(q), types.SimpleNamespace()))
    assert q.answers == 1
    assert "Crie uma busca" in q.edits[-1]


def test_callback_menu_tracked_real(monkeypatch):
    _patch_user(monkeypatch)
    monkeypatch.setattr(handlers_core, "list_wishlists", lambda *_: [types.SimpleNamespace(id="w1", query="civic")])
    monkeypatch.setattr(handlers_core, "list_tracked_listings", lambda _db, **kwargs: (True, f"📌 Rastreados da wishlist {kwargs['wishlist_index']}"))
    q = _CallbackQuery("MENU:TRACKED")
    asyncio.run(handlers_core.cb_menu(_Update(q), types.SimpleNamespace()))
    assert q.answers == 1
    assert "⭐ Anúncios rastreados" in q.edits[-1]
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
    assert "⭐ Anúncios rastreados" in q.edits[-1]


def test_callback_menu_wl_remove_flow(monkeypatch):
    _patch_user(monkeypatch)
    monkeypatch.setattr(handlers_core, "list_wishlists", lambda *_: [types.SimpleNamespace(id="w1", query="civic")])
    q = _CallbackQuery("WL:REMOVE_MENU")
    asyncio.run(handlers_core.cb_menu(_Update(q), types.SimpleNamespace()))
    assert q.answers == 1
    assert "Escolha a busca para remover" in q.edits[-1]

    q2 = _CallbackQuery("WL:REMOVE:1")
    asyncio.run(handlers_core.cb_menu(_Update(q2), types.SimpleNamespace()))
    assert q2.answers == 1
    assert "Remover esta busca?" in q2.edits[-1]

    monkeypatch.setattr(handlers_core, "remove_wishlist", lambda *_args, **_kwargs: (True, "ok"))
    q3 = _CallbackQuery("WL:REMOVE_CONFIRM:1")
    asyncio.run(handlers_core.cb_menu(_Update(q3), types.SimpleNamespace()))
    assert q3.answers == 1
    assert "✅ Busca removida." in q3.edits[-1]


def test_callback_menu_pause_resume_flow(monkeypatch):
    _patch_user(monkeypatch)
    wl = types.SimpleNamespace(id="w1", query="audi a5", is_active=True, filters=[{"field": "price"}], tracked_count=1)
    monkeypatch.setattr(handlers_core, "list_wishlists", lambda *_: [wl])
    monkeypatch.setattr(handlers_core, "get_wishlist_summaries", lambda *_: [{
        "index": 1, "query": wl.query, "filters": [], "tracked_count": wl.tracked_count, "tracked_limit": 3,
        "notifications_24h_count": 0, "is_active": wl.is_active,
    }])

    def _set_state(_db, _user_id, idx, is_active):
        if idx != 1:
            return False, "Busca não encontrada para sua conta."
        wl.is_active = is_active
        return True, wl.query
    monkeypatch.setattr(handlers_core, "set_wishlist_active_state", _set_state)

    q1 = _CallbackQuery("MENU:WISHLISTS")
    asyncio.run(handlers_core.cb_menu(_Update(q1), types.SimpleNamespace(user_data={})))
    assert "⏸️ Pausar busca" in str(q1.edit_payloads[-1]["reply_markup"])

    q2 = _CallbackQuery("WL:PAUSE_MENU")
    asyncio.run(handlers_core.cb_menu(_Update(q2), types.SimpleNamespace(user_data={})))
    assert "Escolha a busca:" in q2.edits[-1]

    q3 = _CallbackQuery("WL:PAUSE:1")
    asyncio.run(handlers_core.cb_menu(_Update(q3), types.SimpleNamespace(user_data={})))
    assert "continuam ocupando vaga do seu plano" in q3.edits[-1]
    assert q3.edit_payloads[-1]["reply_markup"].inline_keyboard[0][0].text == "⏸️ Pausar"

    q4 = _CallbackQuery("WL:PAUSE_CONFIRM:1")
    asyncio.run(handlers_core.cb_menu(_Update(q4), types.SimpleNamespace(user_data={})))
    assert wl.is_active is False

    q5 = _CallbackQuery("MENU:WISHLISTS")
    asyncio.run(handlers_core.cb_menu(_Update(q5), types.SimpleNamespace(user_data={})))
    assert "Status: pausada" in q5.edits[-1]

    q6 = _CallbackQuery("WL:RESUME:1")
    asyncio.run(handlers_core.cb_menu(_Update(q6), types.SimpleNamespace(user_data={})))
    assert q6.edit_payloads[-1]["reply_markup"].inline_keyboard[0][0].text == "▶️ Reativar"

    q7 = _CallbackQuery("WL:RESUME_CONFIRM:1")
    asyncio.run(handlers_core.cb_menu(_Update(q7), types.SimpleNamespace(user_data={})))
    assert wl.is_active is True
    assert wl.filters and wl.tracked_count == 1

    q8 = _CallbackQuery("MENU:WISHLISTS")
    asyncio.run(handlers_core.cb_menu(_Update(q8), types.SimpleNamespace(user_data={})))
    assert "Status: ativa" in q8.edits[-1]


def test_callback_menu_pause_invalid_index(monkeypatch):
    _patch_user(monkeypatch)
    monkeypatch.setattr(handlers_core, "list_wishlists", lambda *_: [types.SimpleNamespace(id="w1", query="civic")])
    q = _CallbackQuery("WL:PAUSE:9")
    asyncio.run(handlers_core.cb_menu(_Update(q), types.SimpleNamespace(user_data={})))
    assert "Busca não encontrada" in q.edits[-1]


def test_run_registers_wl_callback_pattern():
    with open("app/bot/run.py", "r", encoding="utf-8") as fh:
        content = fh.read()
    with open("app/bot/handlers_core.py", "r", encoding="utf-8") as fh:
        handlers_core_content = fh.read()
    assert r'^WL:(BACK|TRACKED|FILTERS_MENU|PAUSE_MENU|PAUSE:\d+|PAUSE_CONFIRM:\d+|RESUME_MENU|RESUME:\d+|RESUME_CONFIRM:\d+|REMOVE_MENU|REMOVE:\d+|REMOVE_CONFIRM:\d+)$' in content
    assert r'^WL:FILTERS:\d+$' in handlers_core_content


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
    assert "Ajuda rápida" in q.edits[-1]
    assert "/menu" in q.edits[-1]


def test_callback_menu_invalid_does_not_break():
    q = _CallbackQuery("MENU:UNKNOWN")
    asyncio.run(handlers_core.cb_menu(_Update(q), types.SimpleNamespace()))
    assert q.answers == 1
    assert "não está mais válida" in q.edits[-1]


def test_callback_menu_fallback_when_edit_fails():
    q = _CallbackQuery("MENU:SEARCH", fail_edit=True)
    asyncio.run(handlers_core.cb_menu(_Update(q), types.SimpleNamespace()))
    assert q.answers == 1
    assert "/buscar civic 2019 até 90000 sp" in q.message.sent[-1]["text"]


def test_quick_commands_still_registered():
    names = {c.command for c in ADVANCED_USER_COMMANDS}
    assert "buscar" in names
    assert "wishlist" in names


def test_wishlists_menu_hides_resume_when_no_paused(monkeypatch):
    _patch_user(monkeypatch)
    monkeypatch.setattr(handlers_core, "get_wishlist_summaries", lambda *_: [{"index":1,"query":"civic","filters":[],"tracked_count":0,"tracked_limit":3,"notifications_24h_count":0,"is_active":True}])
    q = _CallbackQuery("MENU:WISHLISTS")
    asyncio.run(handlers_core.cb_menu(_Update(q), types.SimpleNamespace(user_data={})))
    labels = [btn.text for row in q.edit_payloads[-1]["reply_markup"].inline_keyboard for btn in row]
    assert "▶️ Reativar busca" not in labels


def test_wishlists_menu_hides_pause_when_all_paused(monkeypatch):
    _patch_user(monkeypatch)
    monkeypatch.setattr(handlers_core, "get_wishlist_summaries", lambda *_: [{"index":1,"query":"civic","filters":[],"tracked_count":0,"tracked_limit":3,"notifications_24h_count":0,"is_active":False}])
    q = _CallbackQuery("MENU:WISHLISTS")
    asyncio.run(handlers_core.cb_menu(_Update(q), types.SimpleNamespace(user_data={})))
    labels = [btn.text for row in q.edit_payloads[-1]["reply_markup"].inline_keyboard for btn in row]
    assert "⏸️ Pausar busca" not in labels


def test_callback_menu_filters_flow_opens_selection_and_filter_screen(monkeypatch):
    _patch_user(monkeypatch)
    wl = types.SimpleNamespace(id="w1", query="audi a5", is_active=True)
    monkeypatch.setattr(handlers_core, "list_wishlists", lambda *_: [wl])
    monkeypatch.setattr(handlers_core, "list_filters", lambda *_: [])
    ctx = types.SimpleNamespace(user_data={})
    q1 = _CallbackQuery("WL:FILTERS_MENU")
    asyncio.run(handlers_core.cb_menu(_Update(q1), ctx))
    assert "Escolha a busca:" in q1.edits[-1]
    q2 = _CallbackQuery("WL:FILTERS:1")
    state = asyncio.run(handlers_core.cb_menu(_Update(q2), ctx))
    assert state == handlers_core.MENU_FILTER_SELECT_VALUE
    assert "⚙️ Ajustar filtros" in q2.edits[-1]
