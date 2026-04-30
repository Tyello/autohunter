from __future__ import annotations

import asyncio
import types

from app.bot import handlers_wishlist_ui
from app.notifications.telegram_formatter import format_ad_message


class _Ad:
    title = "Civic"
    price = 100000
    source = "olx"
    url = "https://example.com/1"
    external_id = "E1"
    notification_id = "abc123"
    reason = "new_match"


class _QueryResult:
    def __init__(self, row):
        self._row = row

    def filter(self, *_args, **_kwargs):
        return self

    def first(self):
        return self._row


class _DB:
    def __init__(self, rows):
        self.rows = rows

    def query(self, model):
        return _QueryResult(self.rows.get(model))


class _Session:
    def __init__(self, db):
        self.db = db

    def __enter__(self):
        return self.db

    def __exit__(self, *_):
        return None


class _CallbackQuery:
    def __init__(self, data="TRACK:ADD:n1", fail_edit=False):
        self.data = data
        self.answers = []
        self.edits = []
        self.fail_edit = fail_edit

    async def answer(self, text=None, show_alert=False):
        self.answers.append({"text": text, "show_alert": show_alert})

    async def edit_message_text(self, text):
        if self.fail_edit:
            from telegram.error import BadRequest
            raise BadRequest("message can not be edited")
        self.edits.append(text)


class _Update:
    def __init__(self, q, user_id="u1"):
        self.callback_query = q
        self.effective_chat = types.SimpleNamespace(id=111)
        self.effective_user = types.SimpleNamespace(username="tester")
        self._user_id = user_id


def _patch_common(monkeypatch, *, notification, wishlist, listing, automation=False, add_result=(True, "ok slot 1"), wishlists=None):
    db = _DB({
        handlers_wishlist_ui.Notification: notification,
        handlers_wishlist_ui.Wishlist: wishlist,
        handlers_wishlist_ui.CarListing: listing,
    })
    monkeypatch.setattr(handlers_wishlist_ui, "SessionLocal", lambda: _Session(db))
    monkeypatch.setattr(handlers_wishlist_ui, "get_or_create_user_by_chat", lambda *_: types.SimpleNamespace(id="u1"))
    monkeypatch.setattr(handlers_wishlist_ui, "user_has_tracking_automation", lambda *_args, **_kwargs: automation)
    monkeypatch.setattr(handlers_wishlist_ui, "add_tracked_listing", lambda *_args, **_kwargs: add_result)
    monkeypatch.setattr(handlers_wishlist_ui, "list_wishlists", lambda *_: wishlists if wishlists is not None else [types.SimpleNamespace(id="w1")])


def test_notification_has_track_button():
    payload = format_ad_message(_Ad())
    labels = [b["text"] for b in payload.inline_keyboard[0]]
    assert "⭐ Rastrear" in labels


def test_callback_owner_free_slot_free_plan(monkeypatch):
    _patch_common(
        monkeypatch,
        notification=types.SimpleNamespace(id="n1", wishlist_id="w1", car_listing_id="c1"),
        wishlist=types.SimpleNamespace(id="w1", user_id="u1"),
        listing=types.SimpleNamespace(id="c1", external_id="e1", url="u"),
        automation=False,
        add_result=(True, "slot 1"),
    )
    q = _CallbackQuery()
    asyncio.run(handlers_wishlist_ui.cb_track_add(_Update(q), types.SimpleNamespace()))
    assert q.answers
    assert "Premium" in q.edits[-1]


def test_callback_owner_premium(monkeypatch):
    _patch_common(monkeypatch, notification=types.SimpleNamespace(id="n1", wishlist_id="w1", car_listing_id="c1"), wishlist=types.SimpleNamespace(id="w1", user_id="u1"), listing=types.SimpleNamespace(id="c1", external_id="e1", url="u"), automation=True, add_result=(True, "slot 1"))
    q = _CallbackQuery()
    asyncio.run(handlers_wishlist_ui.cb_track_add(_Update(q), types.SimpleNamespace()))
    assert "automaticamente" in q.edits[-1]


def test_callback_already_tracked(monkeypatch):
    _patch_common(monkeypatch, notification=types.SimpleNamespace(id="n1", wishlist_id="w1", car_listing_id="c1"), wishlist=types.SimpleNamespace(id="w1", user_id="u1"), listing=types.SimpleNamespace(id="c1", external_id="e1", url="u"), add_result=(False, "Esse anúncio já está rastreado no slot 2."))
    q = _CallbackQuery()
    asyncio.run(handlers_wishlist_ui.cb_track_add(_Update(q), types.SimpleNamespace()))
    assert "já está rastreado" in q.edits[-1]


def test_callback_slots_full(monkeypatch):
    _patch_common(monkeypatch, notification=types.SimpleNamespace(id="n1", wishlist_id="w1", car_listing_id="c1"), wishlist=types.SimpleNamespace(id="w1", user_id="u1"), listing=types.SimpleNamespace(id="c1", external_id="e1", url="u"), add_result=(False, "Limite atingido"))
    q = _CallbackQuery()
    asyncio.run(handlers_wishlist_ui.cb_track_add(_Update(q), types.SimpleNamespace()))
    assert "todos os slots" in q.edits[-1]


def test_callback_other_user_blocked(monkeypatch):
    _patch_common(monkeypatch, notification=types.SimpleNamespace(id="n1", wishlist_id="w1", car_listing_id="c1"), wishlist=types.SimpleNamespace(id="w1", user_id="other"), listing=types.SimpleNamespace(id="c1", external_id="e1", url="u"))
    q = _CallbackQuery()
    asyncio.run(handlers_wishlist_ui.cb_track_add(_Update(q), types.SimpleNamespace()))
    assert "sua conta" in q.edits[-1]


def test_callback_notification_not_found(monkeypatch):
    _patch_common(monkeypatch, notification=None, wishlist=None, listing=None)
    q = _CallbackQuery()
    asyncio.run(handlers_wishlist_ui.cb_track_add(_Update(q), types.SimpleNamespace()))
    assert "não encontrei" in q.edits[-1].lower()


def test_callback_listing_missing(monkeypatch):
    _patch_common(monkeypatch, notification=types.SimpleNamespace(id="n1", wishlist_id="w1", car_listing_id="c1"), wishlist=types.SimpleNamespace(id="w1", user_id="u1"), listing=None)
    q = _CallbackQuery()
    asyncio.run(handlers_wishlist_ui.cb_track_add(_Update(q), types.SimpleNamespace()))
    assert "não está mais disponível" in q.edits[-1]


def test_callback_edit_failure_does_not_raise(monkeypatch):
    _patch_common(monkeypatch, notification=types.SimpleNamespace(id="n1", wishlist_id="w1", car_listing_id="c1"), wishlist=types.SimpleNamespace(id="w1", user_id="u1"), listing=types.SimpleNamespace(id="c1", external_id="e1", url="u"), add_result=(True, "slot 1"))
    q = _CallbackQuery(fail_edit=True)
    asyncio.run(handlers_wishlist_ui.cb_track_add(_Update(q), types.SimpleNamespace()))
    assert q.answers
