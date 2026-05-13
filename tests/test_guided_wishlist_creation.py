from __future__ import annotations

import asyncio
import types

from telegram.ext import ConversationHandler

from app.bot import handlers_core


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
    def __init__(self, message: _Message | None = None, q: _CallbackQuery | None = None):
        self.message = message
        self.effective_message = message or _Message()
        self.callback_query = q
        self.effective_chat = types.SimpleNamespace(id=123)
        self.effective_user = types.SimpleNamespace(username="tester")


class _Session:
    def __enter__(self):
        return self

    def __exit__(self, *_):
        return None


def _patch_user(monkeypatch):
    monkeypatch.setattr(handlers_core, "SessionLocal", lambda: _Session())
    monkeypatch.setattr(handlers_core, "get_or_create_user_by_chat", lambda *_: types.SimpleNamespace(id="u1"))


def test_create_flow_query_text_shows_create_options():
    msg = _Message("a5 entre 2017 e 2021")
    ctx = types.SimpleNamespace(user_data={})
    state = asyncio.run(handlers_core.menu_create_wishlist_on_text(_Update(message=msg), ctx))
    assert state == handlers_core.MENU_CREATE_WISHLIST_QUERY
    assert "Entendi sua busca:" in msg.sent[-1]["text"]
    assert "Carro: a5" in msg.sent[-1]["text"]
    assert "Ano entre 2017 e 2021" in msg.sent[-1]["text"]


def test_create_flow_query_text_groups_mixed_implicit_filters():
    msg = _Message("corolla a partir de 2018 até 120000")
    ctx = types.SimpleNamespace(user_data={})
    asyncio.run(handlers_core.menu_create_wishlist_on_text(_Update(message=msg), ctx))
    text = msg.sent[-1]["text"]
    assert "Entendi sua busca:" in text
    assert "Carro: corolla" in text
    assert "Ano a partir de 2018" in text
    assert "Preço até R$ 120.000" in text
    assert "Ano entre 2018 e 120000" not in text


def test_create_flow_query_text_parses_implicit_single_year():
    msg = _Message("a4 avant 2019")
    ctx = types.SimpleNamespace(user_data={})
    asyncio.run(handlers_core.menu_create_wishlist_on_text(_Update(message=msg), ctx))
    text = msg.sent[-1]["text"]
    assert "Entendi sua busca:" in text
    assert "Carro: a4 avant" in text
    assert "Ano 2019" in text


def test_cwl_create_calls_add_wishlist_and_ends(monkeypatch):
    _patch_user(monkeypatch)
    called = {}
    monkeypatch.setattr(handlers_core, "add_wishlist", lambda _db, _uid, q: (called.setdefault("q", q) or True, "ok"))
    ctx = types.SimpleNamespace(user_data={"menu_create_wishlist_query": "civic si"})
    q = _CallbackQuery("CWL:CREATE")
    state = asyncio.run(handlers_core.cb_menu_create_wishlist(_Update(q=q), ctx))
    assert called["q"] == "civic si"
    assert q.answers == 1
    assert state == ConversationHandler.END
    assert "✅ Busca criada com sucesso." in q.edits[-1]["text"]
    buttons = q.edits[-1]["reply_markup"].inline_keyboard
    assert buttons[0][0].text == "🎯 Ver minhas buscas"
    assert buttons[1][0].text == "➕ Criar outra busca"


def test_cwl_create_filters_enters_draft_without_creation(monkeypatch):
    _patch_user(monkeypatch)
    monkeypatch.setattr(handlers_core, "add_wishlist", lambda *_: (_ for _ in ()).throw(AssertionError("must not call")))
    monkeypatch.setattr(handlers_core, "create_wishlist_with_filters", lambda *_: (_ for _ in ()).throw(AssertionError("must not call")))
    ctx = types.SimpleNamespace(user_data={"menu_create_wishlist_query": "civic si"})
    q = _CallbackQuery("CWL:CREATE_FILTERS")
    state = asyncio.run(handlers_core.cb_menu_create_wishlist(_Update(q=q), ctx))
    assert state == handlers_core.MENU_CREATE_WISHLIST_QUERY
    assert ctx.user_data["menu_create_wishlist_draft_filters"] == []
    assert "Filtros para: civic si" in q.edits[-1]["text"]


def test_draft_filter_add_and_remove(monkeypatch):
    ctx = types.SimpleNamespace(user_data={"menu_create_wishlist_query": "civic si", "menu_create_wishlist_draft_filters": []})
    q_type = _CallbackQuery("CWLF:TYPE:state")
    asyncio.run(handlers_core.cb_menu_create_wishlist(_Update(q=q_type), ctx))
    msg = _Message("SP")
    asyncio.run(handlers_core.menu_create_wishlist_on_text(_Update(message=msg), ctx))
    assert ctx.user_data["menu_create_wishlist_draft_filters"][0]["group"] == "state"
    q_list = _CallbackQuery("CWLF:ACTION:list")
    asyncio.run(handlers_core.cb_menu_create_wishlist(_Update(q=q_list), ctx))
    q_rm = _CallbackQuery("CWLF:RM:1")
    asyncio.run(handlers_core.cb_menu_create_wishlist(_Update(q=q_rm), ctx))
    assert ctx.user_data["menu_create_wishlist_draft_filters"] == []


def test_draft_mode_free_text_does_not_override_query():
    ctx = types.SimpleNamespace(user_data={"menu_create_wishlist_query": "civic si", "menu_create_wishlist_draft_filters": []})
    msg = _Message("SP")
    state = asyncio.run(handlers_core.menu_create_wishlist_on_text(_Update(message=msg), ctx))
    assert state == handlers_core.MENU_CREATE_WISHLIST_QUERY
    assert ctx.user_data["menu_create_wishlist_query"] == "civic si"
    assert ctx.user_data["menu_create_wishlist_draft_filters"] == []
    assert "Use os botões para adicionar filtros" in msg.sent[-1]["text"]


def test_draft_done_calls_create_wishlist_with_filters(monkeypatch):
    _patch_user(monkeypatch)
    called = {}

    def _create(_db, _uid, query, filters):
        called["query"] = query
        called["filters"] = filters
        return True, "ok", "wid"

    monkeypatch.setattr(handlers_core, "create_wishlist_with_filters", _create)
    ctx = types.SimpleNamespace(user_data={
        "menu_create_wishlist_query": "civic si",
        "menu_create_wishlist_draft_filters": [{"group": "state", "label": "Estado SP", "filters": [{"field": "state", "operator": "eq", "value": "SP"}]}],
    })
    q = _CallbackQuery("CWLF:DONE")
    state = asyncio.run(handlers_core.cb_menu_create_wishlist(_Update(q=q), ctx))
    assert state == ConversationHandler.END
    assert called["query"] == "civic si"
    assert len(called["filters"]) == 1
    assert "menu_create_wishlist_query" not in ctx.user_data
    assert "menu_create_wishlist_draft_filters" not in ctx.user_data
    assert "✅ Busca criada com sucesso." in q.edits[-1]["text"]


def test_draft_done_without_query_expires_session():
    ctx = types.SimpleNamespace(user_data={"menu_create_wishlist_draft_filters": []})
    q = _CallbackQuery("CWLF:DONE")
    state = asyncio.run(handlers_core.cb_menu_create_wishlist(_Update(q=q), ctx))
    assert state == ConversationHandler.END
    assert ctx.user_data == {}
    assert "Essa etapa expirou." in q.edits[-1]["text"]


def test_draft_cancel_clears_context_and_does_not_create(monkeypatch):
    monkeypatch.setattr(handlers_core, "create_wishlist_with_filters", lambda *_: (_ for _ in ()).throw(AssertionError("must not call")))
    ctx = types.SimpleNamespace(user_data={"menu_create_wishlist_query": "civic si", "menu_create_wishlist_draft_filters": [{"field": "state", "operator": "eq", "value": "SP"}]})
    q = _CallbackQuery("CWLF:CANCEL")
    state = asyncio.run(handlers_core.cb_menu_create_wishlist(_Update(q=q), ctx))
    assert state == ConversationHandler.END
    assert ctx.user_data == {}
    assert "cancelada" in q.edits[-1]["text"]


def test_cwlf_back_keeps_query_and_filters():
    ctx = types.SimpleNamespace(user_data={"menu_create_wishlist_query": "civic", "menu_create_wishlist_draft_filters": [{"group": "state", "label": "Estado SP", "filters": [{"field": "state", "operator": "eq", "value": "SP"}]}], "menu_create_wishlist_draft_filter_type": "state"})
    q = _CallbackQuery("CWLF:BACK")
    state = asyncio.run(handlers_core.cb_menu_create_wishlist(_Update(q=q), ctx))
    assert state == handlers_core.MENU_CREATE_WISHLIST_QUERY
    assert ctx.user_data["menu_create_wishlist_query"] == "civic"
    assert len(ctx.user_data["menu_create_wishlist_draft_filters"]) == 1


def test_draft_price_replaces_previous_group():
    ctx = types.SimpleNamespace(user_data={"menu_create_wishlist_query": "civic", "menu_create_wishlist_draft_filters": []})
    asyncio.run(handlers_core.cb_menu_create_wishlist(_Update(q=_CallbackQuery("CWLF:TYPE:price")), ctx))
    asyncio.run(handlers_core.menu_create_wishlist_on_text(_Update(message=_Message("até 150.000")), ctx))
    asyncio.run(handlers_core.cb_menu_create_wishlist(_Update(q=_CallbackQuery("CWLF:TYPE:price")), ctx))
    asyncio.run(handlers_core.menu_create_wishlist_on_text(_Update(message=_Message("até 56.000")), ctx))
    groups = ctx.user_data["menu_create_wishlist_draft_filters"]
    assert len(groups) == 1
    assert groups[0]["filters"][0]["value"] == "56000"


def test_cwl_create_with_mixed_implicit_filters_calls_create_with_filters(monkeypatch):
    _patch_user(monkeypatch)
    called = {}
    monkeypatch.setattr(handlers_core, "add_wishlist", lambda *_: (_ for _ in ()).throw(AssertionError("must not call")))
    monkeypatch.setattr(handlers_core, "create_wishlist_with_filters", lambda _db, _uid, q, fs: (called.setdefault("query", q) or True, called.setdefault("filters", fs) or "ok", "wid"))
    ctx = types.SimpleNamespace(user_data={})
    asyncio.run(handlers_core.menu_create_wishlist_on_text(_Update(message=_Message("corolla a partir de 2018 até 120000")), ctx))
    state = asyncio.run(handlers_core.cb_menu_create_wishlist(_Update(q=_CallbackQuery("CWL:CREATE")), ctx))
    assert state == ConversationHandler.END
    assert called["query"] == "corolla"
    assert {"field": "year", "operator": "gte", "value": "2018"} in called["filters"]
    assert {"field": "price", "operator": "lte", "value": "120000"} in called["filters"]


def test_cwl_create_is_idempotent_for_repeated_callback(monkeypatch):
    _patch_user(monkeypatch)
    calls = {"count": 0}

    def _create(_db, _uid, query, filters):
        calls["count"] += 1
        return True, "ok", "wid"

    monkeypatch.setattr(handlers_core, "create_wishlist_with_filters", _create)
    monkeypatch.setattr(handlers_core, "add_wishlist", lambda *_: (_ for _ in ()).throw(AssertionError("must not call")))
    ctx = types.SimpleNamespace(user_data={})
    asyncio.run(handlers_core.menu_create_wishlist_on_text(_Update(message=_Message("civic si entre 2014 e 2015")), ctx))
    q1 = _CallbackQuery("CWL:CREATE")
    first_state = asyncio.run(handlers_core.cb_menu_create_wishlist(_Update(q=q1), ctx))
    assert first_state == ConversationHandler.END
    q2 = _CallbackQuery("CWL:CREATE")
    second_state = asyncio.run(handlers_core.cb_menu_create_wishlist(_Update(q=q2), ctx))
    assert second_state == ConversationHandler.END
    assert calls["count"] == 1
    assert "Essa busca já foi criada" in q2.edits[-1]["text"]


def test_cwl_create_plan_limit_shows_only_business_message(monkeypatch):
    _patch_user(monkeypatch)
    monkeypatch.setattr(handlers_core, "add_wishlist", lambda *_: (False, "Você atingiu o limite do plano Free..."))
    ctx = types.SimpleNamespace(user_data={"menu_create_wishlist_query": "civic si"})
    q = _CallbackQuery("CWL:CREATE")
    state = asyncio.run(handlers_core.cb_menu_create_wishlist(_Update(q=q), ctx))
    assert state == handlers_core.MENU_CREATE_WISHLIST_QUERY
    assert "Você atingiu o limite do plano Free" in q.edits[-1]["text"]
    assert "Não consegui concluir essa ação agora" not in q.edits[-1]["text"]
    assert ctx.user_data.get("menu_create_wishlist_completed") is not True


def test_cwl_create_plan_limit_does_not_lock_idempotency_key(monkeypatch):
    _patch_user(monkeypatch)
    calls = {"count": 0}

    def _add(*_args):
        calls["count"] += 1
        return False, "Você atingiu o limite do plano Free..."

    monkeypatch.setattr(handlers_core, "add_wishlist", _add)
    ctx = types.SimpleNamespace(user_data={"menu_create_wishlist_query": "civic si"})

    q1 = _CallbackQuery("CWL:CREATE")
    first_state = asyncio.run(handlers_core.cb_menu_create_wishlist(_Update(q=q1), ctx))
    assert first_state == handlers_core.MENU_CREATE_WISHLIST_QUERY
    assert "Você atingiu o limite do plano Free" in q1.edits[-1]["text"]
    assert "menu_create_wishlist_last_create_key" not in ctx.user_data
    assert ctx.user_data.get("menu_create_wishlist_completed") is not True

    q2 = _CallbackQuery("CWL:CREATE")
    second_state = asyncio.run(handlers_core.cb_menu_create_wishlist(_Update(q=q2), ctx))
    assert second_state == handlers_core.MENU_CREATE_WISHLIST_QUERY
    assert calls["count"] == 2
    assert "Essa busca já foi criada" not in q2.edits[-1]["text"]


def test_cwl_create_partial_enqueue_message_still_confirms_and_is_idempotent(monkeypatch):
    _patch_user(monkeypatch)
    calls = {"count": 0}

    def _add(*_args):
        calls["count"] += 1
        return True, "✅ Busca criada com sucesso.\nNão consegui agendar a primeira busca agora, mas o monitoramento contínuo segue ativo."

    monkeypatch.setattr(handlers_core, "add_wishlist", _add)
    ctx = types.SimpleNamespace(user_data={"menu_create_wishlist_query": "a4 avant 2019"})

    q1 = _CallbackQuery("CWL:CREATE")
    first_state = asyncio.run(handlers_core.cb_menu_create_wishlist(_Update(q=q1), ctx))
    assert first_state == ConversationHandler.END
    first_text = q1.edits[-1]["text"]
    assert first_text.count("✅ Busca criada com sucesso.") == 1
    assert "Wishlist criada" not in first_text
    assert "Não consegui agendar a primeira busca agora" in first_text
    assert "Não consegui concluir essa ação agora" not in first_text

    q2 = _CallbackQuery("CWL:CREATE")
    second_state = asyncio.run(handlers_core.cb_menu_create_wishlist(_Update(q=q2), ctx))
    assert second_state == ConversationHandler.END
    assert calls["count"] == 1
    assert "Essa busca já foi criada" in q2.edits[-1]["text"]


def test_cwlf_done_is_idempotent_for_repeated_callback(monkeypatch):
    _patch_user(monkeypatch)
    calls = {"count": 0}

    def _create(_db, _uid, query, filters):
        calls["count"] += 1
        return True, "ok", "wid"

    monkeypatch.setattr(handlers_core, "create_wishlist_with_filters", _create)
    ctx = types.SimpleNamespace(user_data={
        "menu_create_wishlist_query": "civic si",
        "menu_create_wishlist_draft_filters": [{"group": "state", "label": "Estado: SP", "filters": [{"field": "state", "operator": "eq", "value": "SP"}]}],
    })
    q1 = _CallbackQuery("CWLF:DONE")
    first_state = asyncio.run(handlers_core.cb_menu_create_wishlist(_Update(q=q1), ctx))
    assert first_state == ConversationHandler.END
    q2 = _CallbackQuery("CWLF:DONE")
    second_state = asyncio.run(handlers_core.cb_menu_create_wishlist(_Update(q=q2), ctx))
    assert second_state == ConversationHandler.END
    assert calls["count"] == 1
    assert "Essa busca já foi criada" in q2.edits[-1]["text"]


def test_upgrade_fallback_ends_flow_and_opens_upgrade(monkeypatch):
    called = {"upgrade": 0}

    async def _cmd_upgrade(update, context):
        called["upgrade"] += 1
        await update.message.reply_text("Premium: teste")

    monkeypatch.setattr("app.bot.handlers.cmd_upgrade", _cmd_upgrade)
    msg = _Message("/upgrade")
    ctx = types.SimpleNamespace(user_data={"menu_create_wishlist_query": "civic", "menu_create_wishlist_draft_filters": []})
    state = asyncio.run(handlers_core.menu_upgrade_fallback(_Update(message=msg), ctx))
    assert state == ConversationHandler.END
    assert called["upgrade"] == 1
    assert ctx.user_data == {}
    assert "Premium" in msg.sent[-1]["text"]
