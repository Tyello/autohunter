from __future__ import annotations

import asyncio
import types
from datetime import datetime, timedelta, timezone

from app.bot import handlers_admin
from app.bot.admin_tracking_diagnostics import parse_tracking_window_hours, render_tracking_diagnostics
from app.models.notification import Notification
from app.models.system_log import SystemLog
from app.models.wishlist_tracked_listing import WishlistTrackedListing
from app.services.tracking_diagnostics_service import build_tracking_diagnostics


import uuid
from app.models.user import User
from app.models.wishlist import Wishlist
from app.models.car_listing import CarListing

def test_build_tracking_diagnostics_counts(db):
    now = datetime.now(timezone.utc)
    user = User(id=uuid.uuid4(), telegram_chat_id=501, username="u501", is_active=True)
    wishlist = Wishlist(id=uuid.uuid4(), user_id=user.id, query="civic")
    car_listing = CarListing(id=uuid.uuid4(), source="olx", external_id="x1", title="t", url="https://x", price=100000, location="SP", currency="BRL", extras={})
    car_listing2 = CarListing(id=uuid.uuid4(), source="olx", external_id="x2", title="t2", url="https://x2", price=99000, location="SP", currency="BRL", extras={})
    db.add_all([user, wishlist, car_listing, car_listing2])
    db.commit()
    db.add_all([
        WishlistTrackedListing(wishlist_id=wishlist.id, car_listing_id=car_listing.id, slot=1, listing_status="active", price_drop_alert_enabled=True, last_price_change_direction="dropped", last_price_change_at=now),
        WishlistTrackedListing(wishlist_id=wishlist.id, car_listing_id=car_listing2.id, slot=2, listing_status="inactive", last_observed_price=None, last_price_change_direction="increased", last_price_change_at=now),
        WishlistTrackedListing(wishlist_id=wishlist.id, car_listing_id=None, slot=3, listing_status="orphan", last_seen_at=None),
    ])
    db.add_all([
        Notification(user_id=user.id, wishlist_id=wishlist.id, car_listing_id=car_listing.id, reason="tracked_price_drop", status="queued", created_at=now),
        Notification(user_id=user.id, wishlist_id=wishlist.id, car_listing_id=car_listing.id, reason="tracked_price_drop", status="sent", created_at=now),
        Notification(user_id=user.id, wishlist_id=wishlist.id, car_listing_id=car_listing.id, reason="tracked_price_drop", status="failed", created_at=now - timedelta(hours=30)),
    ])
    db.add(SystemLog(level="info", component="scheduler.tracking", message="tracking_price_sync_finished", created_at=now))
    db.commit()

    payload = build_tracking_diagnostics(db, window_hours=24)
    assert payload["tracked"]["total"] == 3
    assert payload["tracked"]["price_drop_alert_enabled"] == 1
    assert payload["tracked"]["orphan"] == 1
    assert payload["tracked"]["last_observed_price_null"] >= 1
    assert payload["tracked"]["dropped"] == 1
    assert payload["tracked"]["increased"] == 1
    assert payload["price_drop_notifications"]["queued"] == 1
    assert payload["price_drop_notifications"]["sent"] == 1
    assert payload["price_drop_notifications"]["failed"] == 0


def test_renderer_and_parser():
    assert parse_tracking_window_hours([]) == 24
    assert parse_tracking_window_hours(["48"]) == 48
    assert parse_tracking_window_hours(["999"]) == 168
    assert parse_tracking_window_hours(["x"]) == 24
    out = render_tracking_diagnostics({"window_hours": 24, "tracked": {}, "price_drop_notifications": {}, "examples": {"orphans": [{}] * 9}})
    assert "Tracking de preço" in out
    assert "observabilidade apenas" in out
    assert out.count("- {") <= 5


class _Msg:
    def __init__(self): self.sent=[]
    async def reply_text(self, txt): self.sent.append(txt)

class _Update:
    def __init__(self, chat_id=1):
        self.effective_chat = types.SimpleNamespace(id=chat_id)
        self.message = _Msg()

def _ctx(*args): return types.SimpleNamespace(args=list(args))


def test_admin_tracking_auth_and_window(monkeypatch):
    up = _Update(chat_id=9)
    monkeypatch.setattr("app.bot.handlers_admin.is_admin", lambda _cid: False)
    asyncio.run(handlers_admin.cmd_admin(up, _ctx("tracking")))
    assert "Sem permissão" in up.message.sent[-1]

    up2 = _Update(chat_id=1)
    monkeypatch.setattr("app.bot.handlers_admin.is_admin", lambda _cid: True)
    calls = {}
    class _S:
        def __enter__(self): return object()
        def __exit__(self, *a): return False
    monkeypatch.setattr("app.bot.handlers_admin.SessionLocal", _S)
    def _fake(db, window_hours=24):
        calls["w"] = window_hours
        return {"window_hours": window_hours, "tracked": {}, "price_drop_notifications": {}, "last_tracking_job": {}, "examples": {}}
    monkeypatch.setattr("app.bot.handlers_admin.build_tracking_diagnostics", _fake)

    asyncio.run(handlers_admin.cmd_admin(up2, _ctx("tracking", "status", "48")))
    assert calls["w"] == 48
    asyncio.run(handlers_admin.cmd_admin(up2, _ctx("tracking", "status", "999")))
    assert calls["w"] == 168
