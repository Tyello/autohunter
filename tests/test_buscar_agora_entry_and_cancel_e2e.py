from __future__ import annotations

import asyncio
import types

from telegram.ext import ConversationHandler

from app.bot import handlers_buscar_agora, handlers_wishlist_ui


class _Message:
    def __init__(self):
        self.sent: list[dict] = []

    async def reply_text(self, text, reply_markup=None):
        self.sent.append({"text": text, "reply_markup": reply_markup})


class _CallbackQuery:
    def __init__(self):
        self.answered = False

    async def answer(self, text=None, show_alert=False):
        self.answered = True


class _Update:
    def __init__(self, chat_id, q=None):
        self.message = _Message()
        self.effective_message = self.message
        self.callback_query = q
        self.effective_chat = types.SimpleNamespace(id=chat_id)
        self.effective_user = types.SimpleNamespace(username="tester")


def _ctx(user_data=None):
    return types.SimpleNamespace(user_data=user_data if user_data is not None else {})


def test_cmd_buscar_agora_prompts_for_term_and_advances_state():
    update = _Update(chat_id=5001)
    state = asyncio.run(handlers_buscar_agora.cmd_buscar_agora(update, _ctx()))
    assert state == handlers_buscar_agora.BUSCAR_AGORA_TERM
    assert "o que você procura" in update.message.sent[-1]["text"].lower()


def test_cb_buscar_agora_start_answers_callback_and_reuses_prompt():
    q = _CallbackQuery()
    update = _Update(chat_id=5002, q=q)
    state = asyncio.run(handlers_buscar_agora.cb_buscar_agora_start(update, _ctx()))
    assert q.answered is True
    assert state == handlers_buscar_agora.BUSCAR_AGORA_TERM
    assert "o que você procura" in update.message.sent[-1]["text"].lower()


def test_cmd_cancel_ends_conversation_and_clears_wadd_state():
    user_data = {"wadd_query": "civic si"}
    update = _Update(chat_id=5003)
    state = asyncio.run(handlers_wishlist_ui.cmd_cancel(update, _ctx(user_data=user_data)))
    assert state == ConversationHandler.END
    assert "wadd_query" not in user_data
    assert "cancelado" in update.message.sent[-1]["text"].lower()
