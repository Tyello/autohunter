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


class _CallbackQuery:
    def __init__(self, data: str):
        self.data = data
        self.answers: list[tuple] = []
        self.edits: list[dict] = []
        self.message = _Message()

    async def answer(self, text=None, show_alert=False):
        self.answers.append((text, show_alert))

    async def edit_message_text(self, text, reply_markup=None):
        self.edits.append({"text": text, "reply_markup": reply_markup})


class _Update:
    def __init__(self, chat_id, q: _CallbackQuery | None = None):
        self.message = _Message()
        self.effective_message = self.message
        self.callback_query = q
        self.effective_chat = types.SimpleNamespace(id=chat_id)
        self.effective_user = types.SimpleNamespace(username="tester")


class _DBSessionWrapper:
    def __init__(self, db):
        self._db = db

    def __enter__(self):
        return self._db

    def __exit__(self, *_exc):
        return None


def _use_real_db(monkeypatch, db):
    monkeypatch.setattr(handlers_wishlist_ui, "SessionLocal", lambda: _DBSessionWrapper(db))


def _ctx(args=None, user_data=None):
    return types.SimpleNamespace(args=args or [], user_data=user_data if user_data is not None else {})


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


def _make_listing(db, external_id="ext-1", price=Decimal("80000")):
    listing = CarListing(
        id=uuid.uuid4(),
        source="olx",
        external_id=external_id,
        url=f"https://example.com/{external_id}",
        title="Honda Civic Si",
        price=price,
        is_sold=False,
        updated_at=datetime.now(timezone.utc),
    )
    db.add(listing)
    db.commit()
    return listing


def test_wishlist_remove_no_wishlists(db, monkeypatch):
    _use_real_db(monkeypatch, db)
    chat_id = 9001
    _make_user(db, chat_id)

    update = _Update(chat_id)
    asyncio.run(handlers_wishlist_ui.cmd_wishlist_remove(update, _ctx()))
    assert "não tem wishlists" in update.message.sent[-1]["text"].lower()


def test_wishlist_remove_without_index_lists_suggestions(db, monkeypatch):
    _use_real_db(monkeypatch, db)
    chat_id = 9002
    user = _make_user(db, chat_id)
    _make_wishlist(db, user.id, query="civic si")

    update = _Update(chat_id)
    asyncio.run(handlers_wishlist_ui.cmd_wishlist_remove(update, _ctx()))
    text = update.message.sent[-1]["text"]
    assert "/wishlist_remove 1" in text
    assert "civic si" in text


def test_wishlist_remove_by_index_removes_it(db, monkeypatch):
    _use_real_db(monkeypatch, db)
    chat_id = 9003
    user = _make_user(db, chat_id)
    _make_wishlist(db, user.id, query="civic si")

    update = _Update(chat_id)
    asyncio.run(handlers_wishlist_ui.cmd_wishlist_remove(update, _ctx(["1"])))

    check_update = _Update(chat_id)
    asyncio.run(handlers_wishlist_ui.cmd_wishlist_remove(check_update, _ctx()))
    assert "não tem wishlists" in check_update.message.sent[-1]["text"].lower()


def test_wishlist_clear_arms_confirmation(db, monkeypatch):
    _use_real_db(monkeypatch, db)
    chat_id = 9004
    _make_user(db, chat_id)

    user_data: dict = {}
    update = _Update(chat_id)
    asyncio.run(handlers_wishlist_ui.cmd_wishlist_clear(update, _ctx(user_data=user_data)))
    assert user_data["wishlist_clear_armed"] is True
    assert "certeza" in update.message.sent[-1]["text"].lower()


def test_wishlist_clear_cancel_does_not_remove(db, monkeypatch):
    _use_real_db(monkeypatch, db)
    chat_id = 9005
    user = _make_user(db, chat_id)
    _make_wishlist(db, user.id)

    user_data = {"wishlist_clear_armed": True}
    q = _CallbackQuery("W:CLEAR:NO")
    update = _Update(chat_id, q)
    asyncio.run(handlers_wishlist_ui.cb_wishlist_clear(update, _ctx(user_data=user_data)))

    assert "cancelado" in q.edits[-1]["text"].lower()
    assert "wishlist_clear_armed" not in user_data


def test_wishlist_clear_without_arming_is_expired(db, monkeypatch):
    _use_real_db(monkeypatch, db)
    chat_id = 9006
    _make_user(db, chat_id)

    q = _CallbackQuery("W:CLEAR:YES")
    update = _Update(chat_id, q)
    asyncio.run(handlers_wishlist_ui.cb_wishlist_clear(update, _ctx(user_data={})))
    assert "expirada" in q.edits[-1]["text"].lower()


def test_wishlist_clear_confirmed_removes_all(db, monkeypatch):
    _use_real_db(monkeypatch, db)
    chat_id = 9007
    user = _make_user(db, chat_id)
    _make_wishlist(db, user.id, query="civic si")
    _make_wishlist(db, user.id, query="polo gts")

    user_data = {"wishlist_clear_armed": True}
    q = _CallbackQuery("W:CLEAR:YES")
    update = _Update(chat_id, q)
    asyncio.run(handlers_wishlist_ui.cb_wishlist_clear(update, _ctx(user_data=user_data)))
    assert "todas as wishlists foram removidas" in q.edits[-1]["text"].lower()

    check_update = _Update(chat_id)
    asyncio.run(handlers_wishlist_ui.cmd_wishlist_remove(check_update, _ctx()))
    assert "não tem wishlists" in check_update.message.sent[-1]["text"].lower()


def test_wishlist_track_list_shows_tracked_slot(db, monkeypatch):
    _use_real_db(monkeypatch, db)
    chat_id = 9008
    user = _make_user(db, chat_id)
    _make_wishlist(db, user.id)
    _make_listing(db, external_id="civic-track-1")

    add_update = _Update(chat_id)
    asyncio.run(handlers_wishlist_ui.cmd_wishlist_track_add(add_update, _ctx(["1", "civic-track-1"])))

    list_update = _Update(chat_id)
    asyncio.run(handlers_wishlist_ui.cmd_wishlist_track_list(list_update, _ctx(["1"])))
    text = list_update.message.sent[-1]["text"]
    assert "civic" in text.lower() or "slot" in text.lower()


def test_wishlist_track_alert_off_without_automation_still_works(db, monkeypatch):
    """alert_off has no premium gate, unlike alert_on (see cmd_wishlist_track_alert_on)."""
    _use_real_db(monkeypatch, db)
    chat_id = 9009
    user = _make_user(db, chat_id)
    _make_wishlist(db, user.id)
    _make_listing(db, external_id="civic-track-2")

    add_update = _Update(chat_id)
    asyncio.run(handlers_wishlist_ui.cmd_wishlist_track_add(add_update, _ctx(["1", "civic-track-2"])))

    off_update = _Update(chat_id)
    asyncio.run(handlers_wishlist_ui.cmd_wishlist_track_alert_off(off_update, _ctx(["1", "1"])))
    text = off_update.message.sent[-1]["text"].lower()
    assert "premium" not in text


def test_wishlist_track_alert_off_missing_args_shows_usage(db, monkeypatch):
    _use_real_db(monkeypatch, db)
    chat_id = 9010
    _make_user(db, chat_id)

    update = _Update(chat_id)
    asyncio.run(handlers_wishlist_ui.cmd_wishlist_track_alert_off(update, _ctx(["1"])))
    assert "/wishlist_track_alert_off" in update.message.sent[-1]["text"]
