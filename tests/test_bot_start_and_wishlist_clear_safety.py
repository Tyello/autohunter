from __future__ import annotations

import asyncio
import types

from app.bot import handlers_core, handlers_wishlist_ui


class _Message:
    def __init__(self):
        self.sent: list[tuple[str, object | None]] = []

    async def reply_text(self, text, reply_markup=None):
        self.sent.append((text, reply_markup))


class _CallbackQuery:
    def __init__(self, data: str):
        self.data = data
        self.answered = 0
        self.edits: list[str] = []

    async def answer(self):
        self.answered += 1

    async def edit_message_text(self, text: str):
        self.edits.append(text)


class _Update:
    def __init__(self, callback_data: str | None = None):
        self.effective_chat = types.SimpleNamespace(id=111)
        self.effective_user = types.SimpleNamespace(username="tester")
        self.message = _Message()
        self.effective_message = self.message
        self.callback_query = _CallbackQuery(callback_data) if callback_data else None


class _Session:
    def __enter__(self):
        return self

    def __exit__(self, *_):
        return None


def test_start_creates_or_loads_user_without_deleting_wishlist(monkeypatch):
    called = {"get_or_create": 0, "list_wishlists": 0, "remove": 0}

    monkeypatch.setattr(handlers_core, "SessionLocal", lambda: _Session())

    def _fake_get_or_create(_db, _chat_id, _username):
        called["get_or_create"] += 1
        return types.SimpleNamespace(id="u1")

    def _fake_list(_db, _user_id):
        called["list_wishlists"] += 1
        return [types.SimpleNamespace(query="civic")]

    def _fake_remove(*_args, **_kwargs):
        called["remove"] += 1
        raise AssertionError("start não deve remover wishlist")

    monkeypatch.setattr(handlers_core, "get_or_create_user_by_chat", _fake_get_or_create)
    monkeypatch.setattr(handlers_core, "list_wishlists", _fake_list)
    monkeypatch.setattr(handlers_wishlist_ui, "remove_all_wishlists", _fake_remove)
    monkeypatch.setattr(handlers_wishlist_ui, "remove_wishlist", _fake_remove)

    update = _Update()
    context = types.SimpleNamespace(args=[])

    asyncio.run(handlers_core.cmd_start(update, context))

    assert called["get_or_create"] == 1
    assert called["list_wishlists"] == 1
    assert called["remove"] == 0
    assert update.message.sent
    msg = update.message.sent[0][0]
    assert "👋 Garagem Alvo" in msg
    assert "Seu monitoramento já está ativo." in msg
    assert "Use o botão abaixo ou /menu para ver suas buscas, anúncios rastreados, plano atual ou fazer uma busca manual." in msg
    assert "/wishlist_add" not in msg
    assert "/wishlist_help" not in msg


def test_wishlist_clear_requires_fresh_arm_before_delete(monkeypatch):
    monkeypatch.setattr(handlers_wishlist_ui, "SessionLocal", lambda: _Session())

    remove_called = {"n": 0}

    def _fake_remove_all(_db, _user_id):
        remove_called["n"] += 1
        return True, "ok"

    monkeypatch.setattr(handlers_wishlist_ui, "remove_all_wishlists", _fake_remove_all)
    monkeypatch.setattr(
        handlers_wishlist_ui,
        "get_or_create_user_by_chat",
        lambda _db, _chat_id, _username: types.SimpleNamespace(id="u1"),
    )

    # callback YES sem /wishlist_clear antes -> não pode deletar
    update = _Update(callback_data="W:CLEAR:YES")
    context = types.SimpleNamespace(user_data={})
    asyncio.run(handlers_wishlist_ui.cb_wishlist_clear(update, context))

    assert remove_called["n"] == 0
    assert update.callback_query.edits[-1] == "Confirmação expirada. Use /wishlist_clear novamente."

    # arma com comando e confirma -> pode deletar
    update_arm = _Update()
    context2 = types.SimpleNamespace(user_data={})
    asyncio.run(handlers_wishlist_ui.cmd_wishlist_clear(update_arm, context2))
    assert context2.user_data["wishlist_clear_armed"] is True

    update_yes = _Update(callback_data="W:CLEAR:YES")
    asyncio.run(handlers_wishlist_ui.cb_wishlist_clear(update_yes, context2))
    assert remove_called["n"] == 1
    assert update_yes.callback_query.edits[-1] == "🔥 Todas as wishlists foram removidas."


def test_start_without_wishlist_points_to_guided_menu(monkeypatch):
    monkeypatch.setattr(handlers_core, "SessionLocal", lambda: _Session())
    monkeypatch.setattr(
        handlers_core,
        "get_or_create_user_by_chat",
        lambda _db, _chat_id, _username: types.SimpleNamespace(id="u1"),
    )
    monkeypatch.setattr(handlers_core, "list_wishlists", lambda _db, _user_id: [])

    update = _Update()
    context = types.SimpleNamespace(args=[])

    asyncio.run(handlers_core.cmd_start(update, context))

    msg = update.message.sent[0][0]
    assert "👋 Bem-vindo ao Garagem Alvo" in msg
    assert "O buscador do entusiasta." in msg
    assert "toque no botão abaixo e crie sua primeira busca." in msg
    assert "/wishlist_add" not in msg
    assert "/wishlist_help" not in msg
