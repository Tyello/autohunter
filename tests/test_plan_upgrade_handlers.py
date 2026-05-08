from __future__ import annotations

import asyncio
import types
import uuid

from app.bot import handlers
from app.models.account import Account
from app.models.plan import Plan
from app.models.subscription import Subscription
from app.models.user import User


class _Update:
    def __init__(self, callback_query=None):
        self.effective_chat = types.SimpleNamespace(id=123)
        self.effective_user = types.SimpleNamespace(username="tester", first_name="Test")
        self.callback_query = callback_query


class _CallbackQuery:
    def __init__(self, data: str):
        self.data = data
        self.answered = 0
        self.messages = []
        self.message = self

    async def answer(self):
        self.answered += 1

    async def reply_text(self, text, **kwargs):
        self.messages.append({"text": text, **kwargs})


def test_cmd_upgrade_uses_current_commercial_values(monkeypatch):
    sent = []
    async def _reply(_update, text, **_kwargs):
        sent.append(text)
    monkeypatch.setattr(handlers, "reply_text", _reply)
    asyncio.run(handlers.cmd_upgrade(_Update(), types.SimpleNamespace()))
    text = sent[-1]
    assert "Mensal" in text
    assert "Anual" in text
    assert "até 10 wishlists" in text
    assert "até 15 notificações por dia por wishlist" in text
    assert "Os links de pagamento ainda não estão configurados" in text


def test_cmd_upgrade_uses_callback_buttons_when_links_exist(monkeypatch):
    sent = []

    async def _reply(_update, text, **kwargs):
        sent.append({"text": text, "reply_markup": kwargs.get("reply_markup")})

    monkeypatch.setattr(handlers, "reply_text", _reply)
    monkeypatch.setattr(handlers.settings, "mercado_pago_monthly_payment_link", "https://mp/monthly")
    monkeypatch.setattr(handlers.settings, "mercado_pago_annual_payment_link", "https://mp/annual")
    asyncio.run(handlers.cmd_upgrade(_Update(), types.SimpleNamespace()))

    markup = sent[-1]["reply_markup"]
    callback_data = [btn.callback_data for row in markup.inline_keyboard for btn in row]
    assert callback_data == ["UPGRADE:MONTHLY", "UPGRADE:ANNUAL"]


def test_upgrade_callback_monthly_notifies_admin_and_sends_real_link(monkeypatch):
    monkeypatch.setattr(handlers.settings, "mercado_pago_monthly_payment_link", "https://mp/monthly")
    notified = []
    monkeypatch.setattr(handlers, "send_admin_text", lambda text: notified.append(text))
    q = _CallbackQuery("UPGRADE:MONTHLY")
    async def _run():
        await handlers.cb_upgrade_plan_choice(_Update(q), types.SimpleNamespace())
        await asyncio.sleep(0)
    asyncio.run(_run())
    assert q.answered == 1
    assert "Interesse em Premium" in notified[0]
    assert "Plano: Mensal" in notified[0]
    assert q.messages[-1]["reply_markup"].inline_keyboard[0][0].url == "https://mp/monthly"


def test_upgrade_callback_annual_fallback_when_link_missing(monkeypatch):
    monkeypatch.setattr(handlers.settings, "mercado_pago_annual_payment_link", None)
    q = _CallbackQuery("UPGRADE:ANNUAL")
    asyncio.run(handlers.cb_upgrade_plan_choice(_Update(q), types.SimpleNamespace()))
    assert q.answered == 1
    assert "Link de pagamento ainda não configurado" in q.messages[-1]["text"]


def test_upgrade_callback_admin_notify_failure_does_not_block_user(monkeypatch):
    monkeypatch.setattr(handlers.settings, "mercado_pago_annual_payment_link", "https://mp/annual")
    def _raise(_):
        raise RuntimeError("boom")
    monkeypatch.setattr(handlers, "send_admin_text", _raise)
    q = _CallbackQuery("UPGRADE:ANNUAL")
    async def _run():
        await handlers.cb_upgrade_plan_choice(_Update(q), types.SimpleNamespace())
        await asyncio.sleep(0)
    asyncio.run(_run())
    assert q.answered == 1
    assert "Premium Anual" in q.messages[-1]["text"]


def test_cmd_plan_uses_db_capabilities(db, monkeypatch):
    acc = Account(id=uuid.uuid4(), type="personal", name="acc", is_active=True)
    user = User(id=uuid.uuid4(), telegram_chat_id=123, username="tester", is_active=True, account_id=acc.id)
    plan = Plan(code="premium", name="Premium", daily_alert_limit=12, max_wishlists=9, is_active=True)
    db.add_all([acc, user, plan])
    db.commit()
    db.add(Subscription(account_id=acc.id, plan_id=plan.id, status="active", source="seed"))
    db.commit()

    class _Session:
        def __enter__(self):
            return db
        def __exit__(self, *_):
            return None
    monkeypatch.setattr(handlers, "SessionLocal", lambda: _Session())
    monkeypatch.setattr(handlers, "get_or_create_user_by_chat", lambda *_: user)
    sent = []
    async def _reply(_update, text, **_kwargs):
        sent.append(text)
    monkeypatch.setattr(handlers, "reply_text", _reply)
    asyncio.run(handlers.cmd_plan(_Update(), types.SimpleNamespace()))
    text = sent[-1]
    assert "📦 Seu plano: Premium" in text
    assert "Buscas salvas: 0/9" in text
    assert "Alertas: até 12 por dia por busca" in text
