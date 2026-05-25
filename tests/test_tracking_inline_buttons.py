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
        self.message = types.SimpleNamespace(chat=types.SimpleNamespace(id=111))

    async def answer(self, text=None, show_alert=False):
        self.answers.append({"text": text, "show_alert": show_alert})

    async def edit_message_text(self, text, reply_markup=None):
        if self.fail_edit:
            from telegram.error import BadRequest
            raise BadRequest("message can not be edited")
        self.edits.append(text)
        self.reply_markup = reply_markup


class _Update:
    def __init__(self, q, user_id="u1"):
        self.callback_query = q
        self.effective_chat = types.SimpleNamespace(id=111)
        self.effective_user = types.SimpleNamespace(username="tester")
        self._user_id = user_id


def _patch_common(monkeypatch, *, notification, wishlist, listing, automation=False, add_result=None, wishlists=None):
    db = _DB({
        handlers_wishlist_ui.Notification: notification,
        handlers_wishlist_ui.Wishlist: wishlist,
        handlers_wishlist_ui.CarListing: listing,
    })
    monkeypatch.setattr(handlers_wishlist_ui, "SessionLocal", lambda: _Session(db))
    monkeypatch.setattr(handlers_wishlist_ui, "get_or_create_user_by_chat", lambda *_: types.SimpleNamespace(id="u1"))
    monkeypatch.setattr(handlers_wishlist_ui, "user_has_tracking_automation", lambda *_args, **_kwargs: automation)
    if add_result is None:
        add_result = handlers_wishlist_ui.TrackedListingResult(ok=True, status="added", message="ok", slot=1, automation_enabled=automation)
    monkeypatch.setattr(handlers_wishlist_ui, "add_tracked_listing_result", lambda *_args, **_kwargs: add_result)
    monkeypatch.setattr(handlers_wishlist_ui, "list_wishlists", lambda *_: wishlists if wishlists is not None else [types.SimpleNamespace(id="w1")])


class _Bot:
    def __init__(self):
        self.messages = []

    async def send_message(self, chat_id, text):
        self.messages.append({"chat_id": chat_id, "text": text})


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
        add_result=handlers_wishlist_ui.TrackedListingResult(ok=True, status="added", message="slot 1", slot=1, automation_enabled=False),
    )
    q = _CallbackQuery()
    bot = _Bot()
    asyncio.run(handlers_wishlist_ui.cb_track_add(_Update(q), types.SimpleNamespace(bot=bot)))
    assert q.answers
    assert "Premium" in q.edits[-1]
    assert "Vou avisar" not in q.edits[-1]
    assert "Premium" in bot.messages[-1]["text"]


def test_callback_owner_premium(monkeypatch):
    _patch_common(monkeypatch, notification=types.SimpleNamespace(id="n1", wishlist_id="w1", car_listing_id="c1"), wishlist=types.SimpleNamespace(id="w1", user_id="u1"), listing=types.SimpleNamespace(id="c1", external_id="e1", url="u"), automation=True, add_result=handlers_wishlist_ui.TrackedListingResult(ok=True, status="added", message="slot 1", slot=1, automation_enabled=True))
    q = _CallbackQuery()
    bot = _Bot()
    asyncio.run(handlers_wishlist_ui.cb_track_add(_Update(q), types.SimpleNamespace(bot=bot)))
    assert "queda relevante de preço" in q.edits[-1]
    assert "wishlist" in bot.messages[-1]["text"]


def test_callback_already_tracked(monkeypatch):
    _patch_common(monkeypatch, notification=types.SimpleNamespace(id="n1", wishlist_id="w1", car_listing_id="c1"), wishlist=types.SimpleNamespace(id="w1", user_id="u1"), listing=types.SimpleNamespace(id="c1", external_id="e1", url="u"), add_result=handlers_wishlist_ui.TrackedListingResult(ok=False, status="already_tracked", message="Esse anúncio já está rastreado no slot 2.", slot=2, already_tracked=True))
    q = _CallbackQuery()
    bot = _Bot()
    asyncio.run(handlers_wishlist_ui.cb_track_add(_Update(q), types.SimpleNamespace(bot=bot)))
    assert "já está sendo rastreado" in q.edits[-1]
    assert bot.messages


def test_callback_slots_full(monkeypatch):
    _patch_common(monkeypatch, notification=types.SimpleNamespace(id="n1", wishlist_id="w1", car_listing_id="c1"), wishlist=types.SimpleNamespace(id="w1", user_id="u1"), listing=types.SimpleNamespace(id="c1", external_id="e1", url="u"), add_result=handlers_wishlist_ui.TrackedListingResult(ok=False, status="slots_full", message="Limite atingido"))
    q = _CallbackQuery()
    bot = _Bot()
    asyncio.run(handlers_wishlist_ui.cb_track_add(_Update(q), types.SimpleNamespace(bot=bot)))
    assert "já rastreia 3 anúncios" in q.edits[-1]
    assert bot.messages


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
    _patch_common(monkeypatch, notification=types.SimpleNamespace(id="n1", wishlist_id="w1", car_listing_id="c1"), wishlist=types.SimpleNamespace(id="w1", user_id="u1"), listing=types.SimpleNamespace(id="c1", external_id="e1", url="u"), add_result=handlers_wishlist_ui.TrackedListingResult(ok=True, status="added", message="slot 1", slot=1, automation_enabled=False))
    q = _CallbackQuery(fail_edit=True)
    bot = _Bot()
    asyncio.run(handlers_wishlist_ui.cb_track_add(_Update(q), types.SimpleNamespace(bot=bot)))
    assert q.answers
    assert bot.messages


def test_callback_uses_structured_status_not_message(monkeypatch):
    _patch_common(
        monkeypatch,
        notification=types.SimpleNamespace(id="n1", wishlist_id="w1", car_listing_id="c1"),
        wishlist=types.SimpleNamespace(id="w1", user_id="u1"),
        listing=types.SimpleNamespace(id="c1", external_id="e1", url="u"),
        add_result=handlers_wishlist_ui.TrackedListingResult(ok=False, status="slots_full", message="mensagem sem palavra-chave"),
    )
    q = _CallbackQuery()
    asyncio.run(handlers_wishlist_ui.cb_track_add(_Update(q), types.SimpleNamespace()))
    assert "já rastreia 3 anúncios" in q.edits[-1]


def test_callback_addwl_success(monkeypatch):
    _patch_common(monkeypatch, notification=None, wishlist=types.SimpleNamespace(id="w1", user_id="u1"), listing=types.SimpleNamespace(id="c1", external_id="e1", url="u"), add_result=handlers_wishlist_ui.TrackedListingResult(ok=True, status="added", message="slot", slot=1), wishlists=[types.SimpleNamespace(id="w1")])
    q = _CallbackQuery(data="TRACK:ADDWL:w1:c1")
    asyncio.run(handlers_wishlist_ui.cb_track_add(_Update(q), types.SimpleNamespace()))
    assert "Anúncio rastreado" in q.edits[-1]

def test_callback_answered_on_exception(monkeypatch):
    monkeypatch.setattr(handlers_wishlist_ui, "SessionLocal", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    q = _CallbackQuery()
    asyncio.run(handlers_wishlist_ui.cb_track_add(_Update(q), types.SimpleNamespace()))
    assert q.answers


def test_callback_addwl_uses_selected_wishlist(monkeypatch):
    called = {}

    def _add(_db, **kwargs):
        called.update(kwargs)
        return handlers_wishlist_ui.TrackedListingResult(ok=True, status="added", message="slot", slot=1)

    _patch_common(
        monkeypatch,
        notification=None,
        wishlist=types.SimpleNamespace(id="w2", user_id="u1"),
        listing=types.SimpleNamespace(id="c1", external_id="e1", url="u"),
        add_result=handlers_wishlist_ui.TrackedListingResult(ok=True, status="added", message="slot", slot=1),
        wishlists=[types.SimpleNamespace(id="w1"), types.SimpleNamespace(id="w2")],
    )
    monkeypatch.setattr(handlers_wishlist_ui, "add_tracked_listing_result", _add)
    q = _CallbackQuery(data="TRACK:ADDWL:w2:c1")
    asyncio.run(handlers_wishlist_ui.cb_track_add(_Update(q), types.SimpleNamespace()))
    assert called["wishlist_index"] == 2


def test_callback_choose_wishlist_shows_inline_buttons(monkeypatch):
    _patch_common(
        monkeypatch,
        notification=None,
        wishlist=None,
        listing=None,
        wishlists=[
            types.SimpleNamespace(id="w1", is_active=True, query="ativa"),
            types.SimpleNamespace(id="w2", is_active=False, query="pausada"),
        ],
    )
    monkeypatch.setattr(handlers_wishlist_ui, "issue_tracking_callback_token", lambda **_kwargs: "tok123")
    q = _CallbackQuery(data="TRACK:CHOOSE:c1")
    asyncio.run(handlers_wishlist_ui.cb_track_add(_Update(q), types.SimpleNamespace()))
    assert q.edits[-1] == "Escolha uma wishlist para rastrear este anúncio:"
    buttons = [btn for row in q.reply_markup.inline_keyboard for btn in row]
    assert len(buttons) == 1
    assert buttons[0].callback_data == "TRACK:ADDT:tok123"


def test_callback_choose_wishlist_all_paused(monkeypatch):
    _patch_common(
        monkeypatch,
        notification=None,
        wishlist=None,
        listing=None,
        wishlists=[types.SimpleNamespace(id="w1", is_active=False), types.SimpleNamespace(id="w2", is_active=False)],
    )
    q = _CallbackQuery(data="TRACK:CHOOSE:c1")
    asyncio.run(handlers_wishlist_ui.cb_track_add(_Update(q), types.SimpleNamespace()))
    assert "pausadas" in q.edits[-1].lower()


def test_callback_addt_valid(monkeypatch):
    _patch_common(monkeypatch, notification=None, wishlist=types.SimpleNamespace(id="w2", user_id="u1"), listing=types.SimpleNamespace(id="c1", external_id="e1", url="u"), wishlists=[types.SimpleNamespace(id="w1"), types.SimpleNamespace(id="w2")])
    monkeypatch.setattr("app.services.tracking_callback_token_service.resolve_tracking_callback_token", lambda _t: ({"u": "u1", "w": "w2", "l": "c1"}, None))
    q = _CallbackQuery(data="TRACK:ADDT:t1")
    asyncio.run(handlers_wishlist_ui.cb_track_add(_Update(q), types.SimpleNamespace()))
    assert "Anúncio rastreado" in q.edits[-1]


def test_callback_addt_expired(monkeypatch):
    _patch_common(monkeypatch, notification=None, wishlist=None, listing=None)
    monkeypatch.setattr("app.services.tracking_callback_token_service.resolve_tracking_callback_token", lambda _t: (None, "expired"))
    q = _CallbackQuery(data="TRACK:ADDT:t1")
    asyncio.run(handlers_wishlist_ui.cb_track_add(_Update(q), types.SimpleNamespace()))
    assert "expirou" in q.edits[-1].lower()


def test_callback_addt_other_user(monkeypatch):
    _patch_common(monkeypatch, notification=None, wishlist=None, listing=None)
    monkeypatch.setattr("app.services.tracking_callback_token_service.resolve_tracking_callback_token", lambda _t: ({"u": "other", "w": "w1", "l": "c1"}, None))
    q = _CallbackQuery(data="TRACK:ADDT:t1")
    asyncio.run(handlers_wishlist_ui.cb_track_add(_Update(q), types.SimpleNamespace()))
    assert "sua conta" in q.edits[-1].lower()


def test_callback_addt_invalid(monkeypatch):
    _patch_common(monkeypatch, notification=None, wishlist=None, listing=None)
    monkeypatch.setattr("app.services.tracking_callback_token_service.resolve_tracking_callback_token", lambda _t: (None, "invalid"))
    q = _CallbackQuery(data="TRACK:ADDT:t1")
    asyncio.run(handlers_wishlist_ui.cb_track_add(_Update(q), types.SimpleNamespace()))
    assert "não encontrei essa ação" in q.edits[-1].lower()
