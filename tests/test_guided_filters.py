from __future__ import annotations

import asyncio
import types

from telegram.ext import ConversationHandler

from app.bot import handlers_core, handlers_wishlist_ui


class _Message:
    def __init__(self, text: str = ""):
        self.text = text
        self.sent: list[dict] = []

    async def reply_text(self, text, reply_markup=None):
        self.sent.append({"text": text, "reply_markup": reply_markup})


class _CallbackQuery:
    def __init__(self, data: str):
        self.data = data
        self.answers = 0
        self.edits: list[dict] = []
        self.message = _Message()

    async def answer(self):
        self.answers += 1

    async def edit_message_text(self, text, reply_markup=None):
        self.edits.append({"text": text, "reply_markup": reply_markup})


class _Update:
    def __init__(self, q: _CallbackQuery | None = None, text: str = ""):
        self.callback_query = q
        self.message = _Message(text=text)
        self.effective_message = self.message
        self.effective_chat = types.SimpleNamespace(id=123)
        self.effective_user = types.SimpleNamespace(username="tester")


class _Session:
    def __enter__(self):
        return self

    def __exit__(self, *_):
        return None


def _ctx(args=None):
    return types.SimpleNamespace(user_data={}, args=args or [])


def _patch_user(monkeypatch):
    monkeypatch.setattr(handlers_core, "SessionLocal", lambda: _Session())
    monkeypatch.setattr(handlers_core, "get_or_create_user_by_chat", lambda *_: types.SimpleNamespace(id="u1"))


def _start_with_wishlist(monkeypatch):
    _patch_user(monkeypatch)
    monkeypatch.setattr(handlers_core, "list_wishlists", lambda *_: [types.SimpleNamespace(id="wl-1", query="civic si")])
    q = _CallbackQuery("MENU:FILTERS")
    ctx = _ctx()
    asyncio.run(handlers_core.cb_menu(_Update(q=q), ctx))
    return ctx


def test_menu_filters_sem_wishlist(monkeypatch):
    _patch_user(monkeypatch)
    monkeypatch.setattr(handlers_core, "list_wishlists", lambda *_: [])
    q = _CallbackQuery("MENU:FILTERS")
    asyncio.run(handlers_core.cb_menu(_Update(q=q), _ctx()))
    assert "filtros guiados agora" in q.edits[-1]["text"]


def test_menu_filters_com_wishlist_mostra_selecao(monkeypatch):
    _patch_user(monkeypatch)
    monkeypatch.setattr(handlers_core, "list_wishlists", lambda *_: [types.SimpleNamespace(id="1", query="miata")])
    q = _CallbackQuery("MENU:FILTERS")
    asyncio.run(handlers_core.cb_menu(_Update(q=q), _ctx()))
    assert "filtros guiados agora" in q.edits[-1]["text"]


def test_escolher_wishlist_mostra_tipos(monkeypatch):
    ctx = _start_with_wishlist(monkeypatch)
    q = _CallbackQuery("FILTER:WL:1")
    state = asyncio.run(handlers_core.cb_menu_filter(_Update(q=q), ctx))
    assert state == handlers_core.MENU_FILTER_SELECT_VALUE
    assert "Escolha uma ação" in q.edits[-1]["text"]


def test_escolher_acao_adicionar_mostra_tipos(monkeypatch):
    ctx = _start_with_wishlist(monkeypatch)
    asyncio.run(handlers_core.cb_menu_filter(_Update(q=_CallbackQuery("FILTER:WL:1")), ctx))
    q = _CallbackQuery("FILTER:ACTION:add")
    state = asyncio.run(handlers_core.cb_menu_filter(_Update(q=q), ctx))
    assert state == handlers_core.MENU_FILTER_SELECT_VALUE
    assert "Escolha o tipo" in q.edits[-1]["text"]


def test_ver_filtros_sem_filtros(monkeypatch):
    ctx = _start_with_wishlist(monkeypatch)
    asyncio.run(handlers_core.cb_menu_filter(_Update(q=_CallbackQuery("FILTER:WL:1")), ctx))
    monkeypatch.setattr(handlers_core, "list_filters", lambda *_: [])
    q = _CallbackQuery("FILTER:ACTION:list")
    state = asyncio.run(handlers_core.cb_menu_filter(_Update(q=q), ctx))
    assert state == handlers_core.MENU_FILTER_SELECT_VALUE
    assert "ainda não tem filtros" in q.edits[-1]["text"]


def test_filter_mapping_calls_add_filter(monkeypatch):
    cases = [
        ("price_max", "price", "lte"),
        ("year_min", "year", "gte"),
        ("km_max", "mileage_km", "lte"),
        ("city", "city", "eq"),
        ("state", "state", "eq"),
    ]
    for filter_type, expected_field, expected_op in cases:
        ctx = _start_with_wishlist(monkeypatch)
        ctx.user_data["menu_filter_wishlist_index"] = 1
        ctx.user_data["menu_filter_wishlist_id"] = "wl-1"
        ctx.user_data["menu_filter_type"] = filter_type
        called = {}

        def _fake_add_filter(_db, wishlist_id, field, op, value):
            called.update({"wishlist_id": wishlist_id, "field": field, "op": op, "value": value})
            return True, "Filtro adicionado."

        monkeypatch.setattr(handlers_core, "add_filter", _fake_add_filter)
        state = asyncio.run(handlers_core.menu_filter_on_value(_Update(text="90.000"), ctx))
        assert state == ConversationHandler.END
        assert called["wishlist_id"] == "wl-1"
        assert called["field"] == expected_field
        assert called["op"] == expected_op


def test_erro_retry_e_cancelamentos(monkeypatch):
    ctx = _start_with_wishlist(monkeypatch)
    ctx.user_data.update({"menu_filter_wishlist_index": 1, "menu_filter_wishlist_id": "wl-1", "menu_filter_type": "price_max"})
    calls = {"n": 0}

    def _fake_add_filter(_db, *_args):
        calls["n"] += 1
        if calls["n"] == 1:
            return False, "Erro real"
        return True, "Filtro adicionado."

    monkeypatch.setattr(handlers_core, "add_filter", _fake_add_filter)

    u1 = _Update(text="abc")
    state1 = asyncio.run(handlers_core.menu_filter_on_value(u1, ctx))
    assert state1 == handlers_core.MENU_FILTER_SELECT_VALUE
    assert "Erro real" in u1.message.sent[-1]["text"]

    u2 = _Update(text="90000")
    state2 = asyncio.run(handlers_core.menu_filter_on_value(u2, ctx))
    assert state2 == ConversationHandler.END
    assert "Ver filtros: /wishlist_filter_list 1" in u2.message.sent[-1]["text"]

    cctx = _ctx()
    cctx.user_data["menu_filter_type"] = "price_max"
    u3 = _Update(text="/cancelar")
    state3 = asyncio.run(handlers_core.menu_filter_cancel(u3, cctx))
    assert state3 == ConversationHandler.END
    assert cctx.user_data == {}

    bctx = _ctx()
    bctx.user_data["menu_filter_type"] = "price_max"
    q = _CallbackQuery("FILTER:CANCEL")
    state4 = asyncio.run(handlers_core.cb_menu_filter(_Update(q=q), bctx))
    assert state4 == ConversationHandler.END
    assert bctx.user_data == {}


def test_ver_filtros_com_remover(monkeypatch):
    ctx = _start_with_wishlist(monkeypatch)
    asyncio.run(handlers_core.cb_menu_filter(_Update(q=_CallbackQuery("FILTER:WL:1")), ctx))
    monkeypatch.setattr(
        handlers_core,
        "list_filters",
        lambda *_: [types.SimpleNamespace(field="price", operator="lte", value="90000")],
    )
    qlist = _CallbackQuery("FILTER:ACTION:list")
    asyncio.run(handlers_core.cb_menu_filter(_Update(q=qlist), ctx))
    assert "Preço até R$ 90.000" in qlist.edits[-1]["text"]
    assert qlist.edits[-1]["reply_markup"].inline_keyboard[0][0].callback_data == "FILTER:RM:1:1"

    monkeypatch.setattr(handlers_core, "remove_filter", lambda *_: (True, "Filtro removido."))
    seq = {"n": 0}
    def _list_filters_after_remove(*_args):
        seq["n"] += 1
        if seq["n"] == 1:
            return [types.SimpleNamespace(field="price", operator="lte", value="90000")]
        return []
    monkeypatch.setattr(handlers_core, "list_filters", _list_filters_after_remove)
    qrm = _CallbackQuery("FILTER:RM:1:1")
    asyncio.run(handlers_core.cb_menu_filter(_Update(q=qrm), ctx))
    assert "Filtro removido" in qrm.edits[-1]["text"]
    assert qrm.answers == 1


def test_filter_rm_sessao_expirada(monkeypatch):
    _patch_user(monkeypatch)
    q = _CallbackQuery("FILTER:RM:1:1")
    ctx = _ctx()
    state = asyncio.run(handlers_core.cb_menu_filter(_Update(q=q), ctx))
    assert state == ConversationHandler.END
    assert q.answers == 1
    assert q.edits[-1]["text"] == "Sessão expirada. Abra novamente /menu → ⚙️ Filtros."


def test_filter_rm_wishlist_index_invalido(monkeypatch):
    ctx = _start_with_wishlist(monkeypatch)
    asyncio.run(handlers_core.cb_menu_filter(_Update(q=_CallbackQuery("FILTER:WL:1")), ctx))
    q = _CallbackQuery("FILTER:RM:2:1")
    state = asyncio.run(handlers_core.cb_menu_filter(_Update(q=q), ctx))
    assert state == ConversationHandler.END
    assert q.answers == 1
    assert q.edits[-1]["text"] == "Busca não encontrada para sua conta."


def test_filter_rm_filter_index_invalido(monkeypatch):
    ctx = _start_with_wishlist(monkeypatch)
    asyncio.run(handlers_core.cb_menu_filter(_Update(q=_CallbackQuery("FILTER:WL:1")), ctx))
    monkeypatch.setattr(
        handlers_core,
        "list_filters",
        lambda *_: [types.SimpleNamespace(field="price", operator="lte", value="90000")],
    )
    q = _CallbackQuery("FILTER:RM:1:2")
    calls = {"n": 0}
    monkeypatch.setattr(handlers_core, "remove_filter", lambda *_: calls.update(n=calls["n"] + 1))
    state = asyncio.run(handlers_core.cb_menu_filter(_Update(q=q), ctx))
    assert state == handlers_core.MENU_FILTER_SELECT_VALUE
    assert q.answers == 1
    assert q.edits[-1]["text"] == "Filtro não encontrado. Atualize a lista de filtros."
    assert calls["n"] == 0


def test_filter_rm_ownership_mismatch_nao_remove(monkeypatch):
    ctx = _start_with_wishlist(monkeypatch)
    asyncio.run(handlers_core.cb_menu_filter(_Update(q=_CallbackQuery("FILTER:WL:1")), ctx))
    q = _CallbackQuery("FILTER:RM:2:1")
    called = {"n": 0}
    monkeypatch.setattr(handlers_core, "remove_filter", lambda *_: called.update(n=called["n"] + 1))
    asyncio.run(handlers_core.cb_menu_filter(_Update(q=q), ctx))
    assert q.answers == 1
    assert q.edits[-1]["text"] == "Busca não encontrada para sua conta."
    assert called["n"] == 0


def test_filter_rm_lista_mudou_entre_render_e_clique(monkeypatch):
    ctx = _start_with_wishlist(monkeypatch)
    asyncio.run(handlers_core.cb_menu_filter(_Update(q=_CallbackQuery("FILTER:WL:1")), ctx))
    monkeypatch.setattr(handlers_core, "list_filters", lambda *_: [])
    q = _CallbackQuery("FILTER:RM:1:1")
    called = {"n": 0}
    monkeypatch.setattr(handlers_core, "remove_filter", lambda *_: called.update(n=called["n"] + 1))
    state = asyncio.run(handlers_core.cb_menu_filter(_Update(q=q), ctx))
    assert state == handlers_core.MENU_FILTER_SELECT_VALUE
    assert q.answers == 1
    assert "Filtro não encontrado. Atualize a lista de filtros." in q.edits[-1]["text"]
    assert called["n"] == 0


def test_wishlist_filter_add_continua_funcionando(monkeypatch):
    monkeypatch.setattr(handlers_wishlist_ui, "SessionLocal", lambda: _Session())
    monkeypatch.setattr(handlers_wishlist_ui, "get_or_create_user_by_chat", lambda *_: types.SimpleNamespace(id="u1"))
    monkeypatch.setattr(handlers_wishlist_ui, "list_wishlists", lambda *_: [types.SimpleNamespace(id="wl-1", query="q")])
    monkeypatch.setattr(handlers_wishlist_ui, "add_filter", lambda *_: (True, "Filtro adicionado."))
    update = _Update(text="")
    ctx = types.SimpleNamespace(args=["1", "year", "lte", "2015"], user_data={})
    asyncio.run(handlers_wishlist_ui.cmd_wishlist_filter_add(update, ctx))
    assert "Filtro adicionado." in update.message.sent[-1]["text"]
