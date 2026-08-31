from __future__ import annotations

import asyncio
import types
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from app.bot import handlers_wishlist_ui
from app.models.car_listing import CarListing
from app.models.notification import Notification
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
    def __init__(self, chat_id, q: _CallbackQuery):
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


def _ctx():
    return types.SimpleNamespace()


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


def _make_notification(db, user_id, wishlist_id, car_listing_id):
    notif = Notification(
        id=uuid.uuid4(),
        user_id=user_id,
        wishlist_id=wishlist_id,
        car_listing_id=car_listing_id,
        status="sent",
    )
    db.add(notif)
    db.commit()
    return notif


def test_track_add_from_notification_happy_path(db, monkeypatch):
    _use_real_db(monkeypatch, db)
    chat_id = 7101
    user = _make_user(db, chat_id)
    wishlist = _make_wishlist(db, user.id)
    listing = _make_listing(db, external_id="civic-1")
    notif = _make_notification(db, user.id, wishlist.id, listing.id)

    q = _CallbackQuery(f"TRACK:ADD:{notif.id}")
    update = _Update(chat_id, q)
    asyncio.run(handlers_wishlist_ui.cb_track_add(update, _ctx()))

    assert "slot 1/3" in q.edits[-1]["text"]


def test_track_add_notification_not_found(db, monkeypatch):
    _use_real_db(monkeypatch, db)
    chat_id = 7102
    _make_user(db, chat_id)

    q = _CallbackQuery(f"TRACK:ADD:{uuid.uuid4()}")
    update = _Update(chat_id, q)
    asyncio.run(handlers_wishlist_ui.cb_track_add(update, _ctx()))

    assert "não encontrei essa notifica" in q.edits[-1]["text"].lower()


def test_track_add_wishlist_owned_by_other_user_is_rejected(db, monkeypatch):
    _use_real_db(monkeypatch, db)
    owner = _make_user(db, 7103)
    other_chat_id = 7104
    _make_user(db, other_chat_id)
    wishlist = _make_wishlist(db, owner.id)
    listing = _make_listing(db, external_id="civic-2")
    notif = _make_notification(db, owner.id, wishlist.id, listing.id)

    q = _CallbackQuery(f"TRACK:ADD:{notif.id}")
    update = _Update(other_chat_id, q)
    asyncio.run(handlers_wishlist_ui.cb_track_add(update, _ctx()))

    assert "sem permiss" in q.answers[-1][0].lower()
    assert "não encontrada" in q.edits[-1]["text"].lower()


def test_track_choose_without_wishlists_shows_create_prompt(db, monkeypatch):
    _use_real_db(monkeypatch, db)
    chat_id = 7105
    _make_user(db, chat_id)
    listing = _make_listing(db, external_id="civic-3")

    q = _CallbackQuery(f"TRACK:CHOOSE:{listing.id}")
    update = _Update(chat_id, q)
    asyncio.run(handlers_wishlist_ui.cb_track_add(update, _ctx()))

    assert "não tem wishlists" in q.edits[-1]["text"].lower()


def test_track_choose_renders_wishlist_buttons_with_addt_tokens(db, monkeypatch):
    _use_real_db(monkeypatch, db)
    chat_id = 7106
    user = _make_user(db, chat_id)
    _make_wishlist(db, user.id, query="civic si")
    listing = _make_listing(db, external_id="civic-4")

    q = _CallbackQuery(f"TRACK:CHOOSE:{listing.id}")
    update = _Update(chat_id, q)
    asyncio.run(handlers_wishlist_ui.cb_track_add(update, _ctx()))

    markup = q.edits[-1]["reply_markup"]
    buttons = [btn for row in markup.inline_keyboard for btn in row]
    assert len(buttons) == 1
    assert buttons[0].callback_data.startswith("TRACK:ADDT:")


def test_track_add_via_token_round_trip(db, monkeypatch):
    _use_real_db(monkeypatch, db)
    chat_id = 7107
    user = _make_user(db, chat_id)
    wishlist = _make_wishlist(db, user.id, query="civic si")
    listing = _make_listing(db, external_id="civic-5")

    choose_q = _CallbackQuery(f"TRACK:CHOOSE:{listing.id}")
    update = _Update(chat_id, choose_q)
    asyncio.run(handlers_wishlist_ui.cb_track_add(update, _ctx()))
    token_callback_data = choose_q.edits[-1]["reply_markup"].inline_keyboard[0][0].callback_data

    addt_q = _CallbackQuery(token_callback_data)
    addt_update = _Update(chat_id, addt_q)
    asyncio.run(handlers_wishlist_ui.cb_track_add(addt_update, _ctx()))

    assert "slot 1/3" in addt_q.edits[-1]["text"]


def test_track_addwl_direct_happy_path(db, monkeypatch):
    _use_real_db(monkeypatch, db)
    chat_id = 7108
    user = _make_user(db, chat_id)
    wishlist = _make_wishlist(db, user.id)
    listing = _make_listing(db, external_id="civic-6")

    q = _CallbackQuery(f"TRACK:ADDWL:{wishlist.id}:{listing.id}")
    update = _Update(chat_id, q)
    asyncio.run(handlers_wishlist_ui.cb_track_add(update, _ctx()))

    assert "slot 1/3" in q.edits[-1]["text"]


def test_track_addwl_malformed_payload_is_invalid(db, monkeypatch):
    _use_real_db(monkeypatch, db)
    chat_id = 7109
    _make_user(db, chat_id)

    q = _CallbackQuery("TRACK:ADDWL:only-one-part")
    update = _Update(chat_id, q)
    asyncio.run(handlers_wishlist_ui.cb_track_add(update, _ctx()))

    assert "inv" in q.answers[-1][0].lower()


def test_track_unknown_callback_data_is_invalid(db, monkeypatch):
    _use_real_db(monkeypatch, db)
    chat_id = 7110
    _make_user(db, chat_id)

    q = _CallbackQuery("TRACK:BOGUS")
    update = _Update(chat_id, q)
    asyncio.run(handlers_wishlist_ui.cb_track_add(update, _ctx()))

    assert "inv" in q.answers[-1][0].lower()
