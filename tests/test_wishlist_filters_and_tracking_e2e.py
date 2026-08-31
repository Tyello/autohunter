from __future__ import annotations

import asyncio
import types
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from app.bot import handlers_wishlist_ui
from app.models.car_listing import CarListing
from app.models.user import User
from app.models.wishlist import Wishlist


class _Message:
    def __init__(self):
        self.sent: list[dict] = []

    async def reply_text(self, text, reply_markup=None):
        self.sent.append({"text": text, "reply_markup": reply_markup})


class _Update:
    def __init__(self, chat_id):
        self.message = _Message()
        self.effective_message = self.message
        self.callback_query = None
        self.effective_chat = types.SimpleNamespace(id=chat_id)
        self.effective_user = types.SimpleNamespace(username="tester")


class _DBSessionWrapper:
    def __init__(self, db):
        self._db = db

    def __enter__(self):
        return self._db

    def __exit__(self, *_exc):
        return None


def _ctx(args):
    return types.SimpleNamespace(args=args)


def _use_real_db(monkeypatch, db):
    monkeypatch.setattr(handlers_wishlist_ui, "SessionLocal", lambda: _DBSessionWrapper(db))


def _make_user(db, chat_id):
    user = User(id=uuid.uuid4(), telegram_chat_id=chat_id, username="tester", is_active=True)
    db.add(user)
    db.commit()
    return user


def _make_wishlist(db, user_id, query="civic si"):
    wishlist = Wishlist(id=uuid.uuid4(), user_id=user_id, query=query, is_active=True)
    db.add(wishlist)
    db.commit()
    return wishlist


def _make_listing(db, external_id="ext-1", price=Decimal("80000"), is_sold=False):
    listing = CarListing(
        id=uuid.uuid4(),
        source="olx",
        external_id=external_id,
        url=f"https://example.com/{external_id}",
        title="Honda Civic Si",
        price=price,
        is_sold=is_sold,
        updated_at=datetime.now(timezone.utc),
    )
    db.add(listing)
    db.commit()
    return listing


def test_filter_add_then_list_shows_filter(db, monkeypatch):
    _use_real_db(monkeypatch, db)
    chat_id = 6001
    user = _make_user(db, chat_id)
    _make_wishlist(db, user.id)

    update = _Update(chat_id)
    asyncio.run(
        handlers_wishlist_ui.cmd_wishlist_filter_add(update, _ctx(["1", "year", "lte", "2005"]))
    )
    assert "adicionado" in update.message.sent[-1]["text"].lower()

    update2 = _Update(chat_id)
    asyncio.run(handlers_wishlist_ui.cmd_wishlist_filter_list(update2, _ctx(["1"])))
    assert "2005" in update2.message.sent[-1]["text"]


def test_filter_add_rejects_invalid_field(db, monkeypatch):
    _use_real_db(monkeypatch, db)
    chat_id = 6002
    user = _make_user(db, chat_id)
    _make_wishlist(db, user.id)

    update = _Update(chat_id)
    asyncio.run(
        handlers_wishlist_ui.cmd_wishlist_filter_add(update, _ctx(["1", "not_a_field", "eq", "x"]))
    )
    text = update.message.sent[-1]["text"]
    assert "adicionado" not in text.lower()


def test_filter_list_invalid_wishlist_index(db, monkeypatch):
    _use_real_db(monkeypatch, db)
    chat_id = 6003
    _make_user(db, chat_id)

    update = _Update(chat_id)
    asyncio.run(handlers_wishlist_ui.cmd_wishlist_filter_list(update, _ctx(["1"])))
    assert "inválida" in update.message.sent[-1]["text"].lower()


def test_filter_remove_deactivates_filter(db, monkeypatch):
    _use_real_db(monkeypatch, db)
    chat_id = 6004
    user = _make_user(db, chat_id)
    _make_wishlist(db, user.id)

    add_update = _Update(chat_id)
    asyncio.run(
        handlers_wishlist_ui.cmd_wishlist_filter_add(add_update, _ctx(["1", "year", "lte", "2005"]))
    )

    remove_update = _Update(chat_id)
    asyncio.run(handlers_wishlist_ui.cmd_wishlist_filter_remove(remove_update, _ctx(["1", "1"])))
    assert "removido" in remove_update.message.sent[-1]["text"].lower() or "inativo" in remove_update.message.sent[-1]["text"].lower()

    list_update = _Update(chat_id)
    asyncio.run(handlers_wishlist_ui.cmd_wishlist_filter_list(list_update, _ctx(["1"])))
    assert "sem filtros" in list_update.message.sent[-1]["text"].lower()


def test_track_add_by_external_id_uses_slot_one(db, monkeypatch):
    _use_real_db(monkeypatch, db)
    chat_id = 6005
    user = _make_user(db, chat_id)
    _make_wishlist(db, user.id)
    _make_listing(db, external_id="civic-123")

    update = _Update(chat_id)
    asyncio.run(handlers_wishlist_ui.cmd_wishlist_track_add(update, _ctx(["1", "civic-123"])))
    assert "slot 1/3" in update.message.sent[-1]["text"]


def test_track_add_unknown_listing_reports_not_found(db, monkeypatch):
    _use_real_db(monkeypatch, db)
    chat_id = 6006
    user = _make_user(db, chat_id)
    _make_wishlist(db, user.id)

    update = _Update(chat_id)
    asyncio.run(handlers_wishlist_ui.cmd_wishlist_track_add(update, _ctx(["1", "does-not-exist"])))
    assert "não encontrei" in update.message.sent[-1]["text"].lower()


def test_track_add_second_listing_hits_free_plan_total_cap(db, monkeypatch):
    """Free plan caps total tracked listings at 1 across all wishlists (plan_capabilities defaults)."""
    _use_real_db(monkeypatch, db)
    chat_id = 6007
    user = _make_user(db, chat_id)
    _make_wishlist(db, user.id)

    _make_listing(db, external_id="ext-0")
    first_update = _Update(chat_id)
    asyncio.run(handlers_wishlist_ui.cmd_wishlist_track_add(first_update, _ctx(["1", "ext-0"])))
    assert "slot 1/3" in first_update.message.sent[-1]["text"]

    _make_listing(db, external_id="ext-overflow")
    update = _Update(chat_id)
    asyncio.run(handlers_wishlist_ui.cmd_wishlist_track_add(update, _ctx(["1", "ext-overflow"])))
    assert "limite do plano" in update.message.sent[-1]["text"].lower()


def test_track_remove_by_slot_frees_slot_for_reuse(db, monkeypatch):
    _use_real_db(monkeypatch, db)
    chat_id = 6008
    user = _make_user(db, chat_id)
    _make_wishlist(db, user.id)
    _make_listing(db, external_id="ext-a")

    add_update = _Update(chat_id)
    asyncio.run(handlers_wishlist_ui.cmd_wishlist_track_add(add_update, _ctx(["1", "ext-a"])))
    assert "slot 1/3" in add_update.message.sent[-1]["text"]

    remove_update = _Update(chat_id)
    asyncio.run(handlers_wishlist_ui.cmd_wishlist_track_remove(remove_update, _ctx(["1", "1"])))
    remove_text = remove_update.message.sent[-1]["text"].lower()
    assert "erro" not in remove_text and "não" not in remove_text

    _make_listing(db, external_id="ext-b")
    readd_update = _Update(chat_id)
    asyncio.run(handlers_wishlist_ui.cmd_wishlist_track_add(readd_update, _ctx(["1", "ext-b"])))
    assert "slot 1/3" in readd_update.message.sent[-1]["text"]


def test_track_alert_on_blocked_without_automation_capability(db, monkeypatch):
    _use_real_db(monkeypatch, db)
    chat_id = 6009
    user = _make_user(db, chat_id)
    _make_wishlist(db, user.id)
    _make_listing(db, external_id="ext-c")

    add_update = _Update(chat_id)
    asyncio.run(handlers_wishlist_ui.cmd_wishlist_track_add(add_update, _ctx(["1", "ext-c"])))

    alert_update = _Update(chat_id)
    asyncio.run(handlers_wishlist_ui.cmd_wishlist_track_alert_on(alert_update, _ctx(["1", "1"])))
    text = alert_update.message.sent[-1]["text"]
    assert "premium" in text.lower()
