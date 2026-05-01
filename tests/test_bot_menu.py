from __future__ import annotations

import asyncio
import types

from app.bot import handlers_core
from app.bot.commands import COMMANDS


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

    async def edit_message_text(self, text):
        if self.fail_edit:
            raise RuntimeError("cannot edit")
        self.edits.append(text)


class _Update:
    def __init__(self, q: _CallbackQuery | None = None):
        self.message = _Message()
        self.effective_message = self.message
        self.callback_query = q


def test_cmd_menu_renders_buttons():
    update = _Update()
    asyncio.run(handlers_core.cmd_menu(update, types.SimpleNamespace()))

    payload = update.message.sent[-1]
    assert "AutoHunter" in payload["text"]
    markup = payload["reply_markup"]
    callback_data = [btn.callback_data for row in markup.inline_keyboard for btn in row]
    assert callback_data == [
        "MENU:SEARCH",
        "MENU:WISHLISTS",
        "MENU:TRACKED",
        "MENU:FILTERS",
        "MENU:HELP",
    ]


def test_callback_menu_search():
    q = _CallbackQuery("MENU:SEARCH")
    asyncio.run(handlers_core.cb_menu(_Update(q), types.SimpleNamespace()))
    assert q.answers == 1
    assert "/buscar civic si" in q.edits[-1]


def test_callback_menu_wishlists():
    q = _CallbackQuery("MENU:WISHLISTS")
    asyncio.run(handlers_core.cb_menu(_Update(q), types.SimpleNamespace()))
    assert q.answers == 1
    assert "/wishlist" in q.edits[-1]


def test_callback_menu_tracked():
    q = _CallbackQuery("MENU:TRACKED")
    asyncio.run(handlers_core.cb_menu(_Update(q), types.SimpleNamespace()))
    assert q.answers == 1
    assert "/wishlist_track_list" in q.edits[-1]


def test_callback_menu_filters():
    q = _CallbackQuery("MENU:FILTERS")
    asyncio.run(handlers_core.cb_menu(_Update(q), types.SimpleNamespace()))
    assert q.answers == 1
    assert "/wishlist_filter_list <n>" in q.edits[-1]


def test_callback_menu_help():
    q = _CallbackQuery("MENU:HELP")
    asyncio.run(handlers_core.cb_menu(_Update(q), types.SimpleNamespace()))
    assert q.answers == 1
    assert "/help" in q.edits[-1]


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
    names = {c.command for c in COMMANDS}
    assert "buscar" in names
    assert "wishlist" in names
