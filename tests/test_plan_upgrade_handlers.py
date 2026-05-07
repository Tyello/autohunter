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
    def __init__(self):
        self.effective_chat = types.SimpleNamespace(id=123)
        self.effective_user = types.SimpleNamespace(username="tester")


def test_cmd_upgrade_uses_current_commercial_values(monkeypatch):
    sent = []
    async def _reply(_update, text, **_kwargs):
        sent.append(text)
    monkeypatch.setattr(handlers, "reply_text", _reply)
    asyncio.run(handlers.cmd_upgrade(_Update(), types.SimpleNamespace()))
    text = sent[-1]
    assert "Mensal" in text
    assert "Anual" in text
    assert "até 15 buscas salvas" in text
    assert "200 alertas por dia por busca" in text
    assert "Os links de pagamento ainda não estão disponíveis" in text


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
