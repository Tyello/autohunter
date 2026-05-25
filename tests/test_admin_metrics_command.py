from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app.bot import handlers_admin
from app.bot.admin_handlers_metrics import admin_metrics
from app.models.account import Account
from app.models.car_listing import CarListing
from app.models.notification import Notification
from app.models.plan import Plan
from app.models.subscription import Subscription
from app.models.user import User
from app.models.wishlist import Wishlist


class _Msg:
    def __init__(self):
        self.sent: list[str] = []

    async def reply_text(self, text, **_kwargs):
        self.sent.append(text)


class _Up:
    def __init__(self, chat_id=1):
        self.effective_chat = SimpleNamespace(id=chat_id)
        self.message = _Msg()


def _ctx(*args):
    return SimpleNamespace(args=list(args))


def _bind_session(monkeypatch, db):
    class _S:
        def __enter__(self):
            return db

        def __exit__(self, *_args):
            return False

    import app.bot.admin_handlers_metrics as m

    monkeypatch.setattr(m, "SessionLocal", lambda: _S())


def test_admin_metrics_render_empty_base(monkeypatch, db):
    _bind_session(monkeypatch, db)
    up = _Up()
    asyncio.run(admin_metrics(up, []))
    txt = up.message.sent[-1]
    assert "📊 Métricas — Garagem Alvo" in txt
    assert "Total: 0 · Novos 7d: 0" in txt
    assert "Backlog atual: 0" in txt
    assert "Sources (7d)" in txt
    assert "\n-" in txt


def test_admin_metrics_counts_and_sources(monkeypatch, db):
    _bind_session(monkeypatch, db)
    now = datetime.now(timezone.utc)

    free = User(id=uuid.uuid4(), telegram_chat_id=1001, username="free", is_active=True)
    new_user = User(id=uuid.uuid4(), telegram_chat_id=1002, username="new", is_active=True, created_at=now - timedelta(days=2))
    acc = Account(id=uuid.uuid4(), type="personal", name="acc")
    premium = User(id=uuid.uuid4(), telegram_chat_id=1003, username="premium", is_active=True, account_id=acc.id)
    db.add_all([free, new_user, acc, premium])

    p_free = Plan(id=uuid.uuid4(), code="free", name="Free", daily_alert_limit=1, max_wishlists=2, is_active=True)
    p_premium = Plan(id=uuid.uuid4(), code="premium", name="Premium", daily_alert_limit=10, max_wishlists=10, is_active=True)
    db.add_all([p_free, p_premium])
    db.add(
        Subscription(
            id=uuid.uuid4(),
            account_id=acc.id,
            plan_id=p_premium.id,
            status="active",
            starts_at=now - timedelta(days=3),
            current_period_end=now + timedelta(days=30),
        )
    )

    wl1 = Wishlist(id=uuid.uuid4(), user_id=free.id, query="civic", is_active=True, created_at=now - timedelta(days=1))
    wl2 = Wishlist(id=uuid.uuid4(), user_id=premium.id, query="corolla", is_active=True)
    db.add_all([wl1, wl2])

    l1 = CarListing(id=uuid.uuid4(), source="mercadolivre", external_id="m1", title="A", url="https://a")
    l2 = CarListing(id=uuid.uuid4(), source="olx", external_id="o1", title="B", url="https://b")
    db.add_all([l1, l2])

    db.add_all([
        Notification(id=uuid.uuid4(), user_id=free.id, wishlist_id=wl1.id, car_listing_id=l1.id, status="sent", sent_at=now - timedelta(hours=2)),
        Notification(id=uuid.uuid4(), user_id=premium.id, wishlist_id=wl2.id, car_listing_id=l1.id, status="sent", sent_at=now - timedelta(days=2)),
        Notification(id=uuid.uuid4(), user_id=premium.id, wishlist_id=wl2.id, car_listing_id=l2.id, status="sent", sent_at=now - timedelta(days=5)),
        Notification(id=uuid.uuid4(), user_id=premium.id, wishlist_id=wl2.id, car_listing_id=l2.id, status="queued"),
    ])
    db.commit()

    up = _Up()
    asyncio.run(admin_metrics(up, []))
    txt = up.message.sent[-1]
    assert "Total: 3 · Novos 7d: 3" in txt
    assert "Com busca ativa: 2 (67%)" in txt
    assert "Receberam alerta 7d: 2 (67%)" in txt
    assert "Criadas 7d: 2 · Total ativas: 2" in txt
    assert "Enviados hoje: 1 · Enviados 7d: 3" in txt
    assert "Backlog atual: 1" in txt
    assert "Free: 2 · Premium: 1 (33%)" in txt
    assert "mercadolivre: 2 alertas" in txt
    assert "olx: 1 alertas" in txt


def test_cmd_admin_metrics_dispatch(monkeypatch):
    monkeypatch.setattr(handlers_admin, "is_admin", lambda _cid: True)
    called = {"args": None}

    async def _fake_admin_metrics(update, raw_args):
        called["args"] = raw_args
        await update.message.reply_text("ok")

    monkeypatch.setattr(handlers_admin, "admin_metrics", _fake_admin_metrics)
    up = _Up()
    asyncio.run(handlers_admin.cmd_admin(up, _ctx("metrics", "x")))
    assert called["args"] == ["x"]
    assert up.message.sent[-1] == "ok"
