from __future__ import annotations

import asyncio
import types

from app.bot import handlers_wishlist_ui
from app.models.fipe_lookup_request import FipeLookupRequest
from app.models.user import User
from app.models.wishlist import Wishlist


class _Message:
    def __init__(self, text=""):
        self.text = text
        self.sent: list[dict] = []

    async def reply_text(self, text, reply_markup=None):
        self.sent.append({"text": text, "reply_markup": reply_markup})


class _CallbackQuery:
    def __init__(self, data: str):
        self.data = data
        self.answers = 0
        self.edits: list[str] = []
        self.message = _Message()

    async def answer(self):
        self.answers += 1

    async def edit_message_text(self, text, reply_markup=None):
        self.edits.append(text)


class _Update:
    def __init__(self, chat_id, text="", q: _CallbackQuery | None = None, username="tester"):
        self.message = _Message(text)
        self.effective_message = self.message
        self.callback_query = q
        self.effective_chat = types.SimpleNamespace(id=chat_id)
        self.effective_user = types.SimpleNamespace(username=username)


class _DBSessionWrapper:
    """Wraps the pytest `db` fixture so `with SessionLocal() as db:` doesn't close it between calls."""

    def __init__(self, db):
        self._db = db

    def __enter__(self):
        return self._db

    def __exit__(self, *_exc):
        return None


def _ctx():
    return types.SimpleNamespace(args=[], user_data={})


def _use_real_db(monkeypatch, db):
    monkeypatch.setattr(handlers_wishlist_ui, "SessionLocal", lambda: _DBSessionWrapper(db))


def test_wishlist_add_wizard_creates_wishlist_and_enqueues_fipe_lookup(db, monkeypatch):
    _use_real_db(monkeypatch, db)
    chat_id = 5001
    context = _ctx()

    update_start = _Update(chat_id)
    state = asyncio.run(handlers_wishlist_ui.cmd_wishlist_add_start(update_start, context))
    assert state == handlers_wishlist_ui.WADD_QUERY

    update_query = _Update(chat_id, text="civic si")
    asyncio.run(handlers_wishlist_ui.cmd_wishlist_add_on_query(update_query, context))
    assert context.user_data["wadd_query"] == "civic si"

    q = _CallbackQuery("W:ADD:SAVE")
    update_confirm = _Update(chat_id, q=q)
    asyncio.run(handlers_wishlist_ui.cb_wishlist_add_confirm(update_confirm, context))

    assert "wadd_query" not in context.user_data
    assert "sucesso" in q.edits[-1].lower() or "criada" in q.edits[-1].lower()

    user = db.query(User).filter(User.telegram_chat_id == chat_id).one()
    wishlist = db.query(Wishlist).filter(Wishlist.user_id == user.id).one()
    assert wishlist.query == "civic si"

    fipe_request = db.query(FipeLookupRequest).filter(FipeLookupRequest.wishlist_id == wishlist.id).first()
    assert fipe_request is not None
    assert fipe_request.status == "pending"


def test_wishlist_add_on_query_rejects_short_text(db, monkeypatch):
    _use_real_db(monkeypatch, db)
    context = _ctx()
    update = _Update(5002, text="ab")
    state = asyncio.run(handlers_wishlist_ui.cmd_wishlist_add_on_query(update, context))

    assert state == handlers_wishlist_ui.WADD_QUERY
    assert "curto" in update.message.sent[-1]["text"].lower()
    assert "wadd_query" not in context.user_data


def test_wishlist_add_confirm_cancel_does_not_create_wishlist(db, monkeypatch):
    _use_real_db(monkeypatch, db)
    chat_id = 5003
    context = _ctx()
    context.user_data["wadd_query"] = "gol g5"

    q = _CallbackQuery("W:ADD:CANCEL")
    update = _Update(chat_id, q=q)
    asyncio.run(handlers_wishlist_ui.cb_wishlist_add_confirm(update, context))

    assert "Cancelado" in q.edits[-1]
    assert "wadd_query" not in context.user_data
    assert db.query(Wishlist).count() == 0


def test_wishlist_add_confirm_expired_session_when_no_query_stored(db, monkeypatch):
    _use_real_db(monkeypatch, db)
    context = _ctx()
    q = _CallbackQuery("W:ADD:SAVE")
    update = _Update(5004, q=q)
    asyncio.run(handlers_wishlist_ui.cb_wishlist_add_confirm(update, context))

    assert "expirada" in q.edits[-1].lower()
    assert db.query(Wishlist).count() == 0


def test_wishlist_add_start_blocks_at_max_wishlists(db, monkeypatch):
    _use_real_db(monkeypatch, db)
    chat_id = 5005
    context = _ctx()

    user = User(id=__import__("uuid").uuid4(), telegram_chat_id=chat_id, username="tester", is_active=True)
    db.add(user)
    db.commit()
    for i in range(2):  # DEFAULT_MAX_WISHLISTS_PER_USER == 2
        db.add(Wishlist(id=__import__("uuid").uuid4(), user_id=user.id, query=f"carro {i}", is_active=True))
    db.commit()

    update = _Update(chat_id)
    state = asyncio.run(handlers_wishlist_ui.cmd_wishlist_add_start(update, context))

    assert state == handlers_wishlist_ui.ConversationHandler.END
    text = update.message.sent[-1]["text"]
    assert "limite" in text.lower() or "máximo" in text.lower()
