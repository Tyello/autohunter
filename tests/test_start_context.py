from __future__ import annotations

import asyncio
import types

from app.bot import handlers_core
from app.bot.renderers import render_start_text


class _Message:
    def __init__(self):
        self.sent: list[dict] = []

    async def reply_text(self, text, reply_markup=None):
        self.sent.append({"text": text, "reply_markup": reply_markup})


class _Update:
    def __init__(self):
        self.message = _Message()
        self.effective_message = self.message
        self.effective_chat = types.SimpleNamespace(id=123)
        self.effective_user = types.SimpleNamespace(username="tester")


class _Session:
    def __enter__(self):
        return self

    def __exit__(self, *_):
        return None


def _patch_base(monkeypatch):
    monkeypatch.setattr(handlers_core, "SessionLocal", lambda: _Session())
    monkeypatch.setattr(handlers_core, "get_or_create_user_by_chat", lambda *_: types.SimpleNamespace(id="u1"))


def test_render_start_text_onboarding_ignores_context():
    text = render_start_text(0, context_line="qualquer coisa")
    assert "Bem-vindo ao Garagem Alvo" in text
    assert "qualquer coisa" not in text


def test_render_start_text_with_active_wishlists_without_context():
    text = render_start_text(2)
    assert "Seu monitoramento já está ativo" in text
    assert "Você tem 2 busca(s) ativa(s)." in text


def test_render_start_text_with_context_line():
    ctx = "Enviei 4 alerta(s) para você nos últimos 7 dias."
    text = render_start_text(2, context_line=ctx)
    assert "Você tem 2 busca(s) ativa(s)." in text
    assert ctx in text


def test_cmd_start_with_active_wishlist_includes_recent_alerts(monkeypatch):
    _patch_base(monkeypatch)
    monkeypatch.setattr(handlers_core, "list_wishlists", lambda *_: [types.SimpleNamespace(id="w1", is_active=True)])
    monkeypatch.setattr(handlers_core, "count_notifications_sent_last_n_days", lambda *_args, **_kwargs: 3)

    update = _Update()
    asyncio.run(handlers_core.cmd_start(update, types.SimpleNamespace()))

    payload = update.message.sent[-1]
    assert "Você tem 1 busca(s) ativa(s)." in payload["text"]
    assert "Enviei 3 alerta(s)" in payload["text"]
    callback_data = [btn.callback_data for row in payload["reply_markup"].inline_keyboard for btn in row]
    assert "MENU:WISHLISTS" in callback_data


def test_cmd_start_with_paused_wishlist_is_not_onboarding(monkeypatch):
    _patch_base(monkeypatch)
    monkeypatch.setattr(handlers_core, "list_wishlists", lambda *_: [types.SimpleNamespace(id="w1", is_active=False)])

    update = _Update()
    asyncio.run(handlers_core.cmd_start(update, types.SimpleNamespace()))

    payload = update.message.sent[-1]
    assert "Bem-vindo ao Garagem Alvo" not in payload["text"]
    assert "buscas salvas, mas nenhuma ativa" in payload["text"]
    callback_data = [btn.callback_data for row in payload["reply_markup"].inline_keyboard for btn in row]
    assert "MENU:WISHLISTS" in callback_data
