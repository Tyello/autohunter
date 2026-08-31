from __future__ import annotations

import asyncio
import types

from app.bot import handlers, handlers_core, handlers_misc


class _Message:
    def __init__(self):
        self.sent: list[dict] = []

    async def reply_text(self, text, reply_markup=None):
        self.sent.append({"text": text, "reply_markup": reply_markup})


class _Update:
    def __init__(self, chat_id=123, username="tester"):
        self.message = _Message()
        self.effective_message = self.message
        self.callback_query = None
        self.effective_chat = types.SimpleNamespace(id=chat_id)
        self.effective_user = types.SimpleNamespace(username=username)


class _Session:
    def __enter__(self):
        return self

    def __exit__(self, *_):
        return None


def _ctx(args=None):
    return types.SimpleNamespace(args=args or [])


def _patch_user(monkeypatch, module, user=None):
    monkeypatch.setattr(module, "SessionLocal", lambda: _Session())
    monkeypatch.setattr(
        module, "get_or_create_user_by_chat", lambda *_: user or types.SimpleNamespace(id="u1")
    )


def test_cmd_help_returns_help_text():
    update = _Update()
    asyncio.run(handlers_core.cmd_help(update, _ctx()))
    assert update.message.sent
    assert update.message.sent[-1]["text"]


def test_cmd_wishlist_help_returns_text():
    update = _Update()
    asyncio.run(handlers_core.cmd_wishlist_help(update, _ctx()))
    assert update.message.sent
    assert update.message.sent[-1]["text"]


def test_cmd_version_returns_text():
    update = _Update()
    asyncio.run(handlers_core.cmd_version(update, _ctx()))
    assert "AutoHunter" in update.message.sent[-1]["text"]


def test_cmd_me_returns_chat_id():
    update = _Update(chat_id=999)
    asyncio.run(handlers_misc.cmd_me(update, _ctx()))
    assert update.message.sent[-1]["text"] == "chat_id=999"


def test_cmd_status_renders_plan_and_wishlist_count(monkeypatch):
    _patch_user(monkeypatch, handlers_core)
    monkeypatch.setattr(
        handlers_core,
        "list_wishlists",
        lambda *_: [types.SimpleNamespace(id="w1"), types.SimpleNamespace(id="w2")],
    )
    monkeypatch.setattr(
        handlers_core,
        "get_user_plan_snapshot",
        lambda *_: {"max_wishlists": 5, "daily_alert_limit": 10, "plan_code": "premium"},
    )
    update = _Update()
    asyncio.run(handlers_core.cmd_status(update, _ctx()))

    text = update.message.sent[-1]["text"]
    assert "premium" in text
    assert "2/5" in text
    assert "10" in text


def test_cmd_status_handles_missing_daily_limit(monkeypatch):
    _patch_user(monkeypatch, handlers_core)
    monkeypatch.setattr(handlers_core, "list_wishlists", lambda *_: [])
    monkeypatch.setattr(
        handlers_core,
        "get_user_plan_snapshot",
        lambda *_: {"max_wishlists": 1, "daily_alert_limit": None, "plan_code": None},
    )
    update = _Update()
    asyncio.run(handlers_core.cmd_status(update, _ctx()))

    text = update.message.sent[-1]["text"]
    assert "free" in text
    assert "—" in text


def test_cmd_digest_status_default(monkeypatch):
    _patch_user(monkeypatch, handlers_core)
    pref = types.SimpleNamespace(
        weekly_digest_enabled=True,
        digest_days=7,
        digest_limit=10,
        last_digest_sent_at=None,
        last_digest_previewed_at=None,
    )
    monkeypatch.setattr(handlers_core, "get_or_create_digest_preference", lambda *_: pref)
    update = _Update()
    asyncio.run(handlers_core.cmd_digest(update, _ctx()))

    text = update.message.sent[-1]["text"]
    assert "ativado" in text


def test_cmd_digest_on_off(monkeypatch):
    _patch_user(monkeypatch, handlers_core)
    pref = types.SimpleNamespace(weekly_digest_enabled=False)
    monkeypatch.setattr(handlers_core, "get_or_create_digest_preference", lambda *_: pref)
    calls = []
    monkeypatch.setattr(
        handlers_core, "set_weekly_digest_enabled", lambda db, uid, val: calls.append(val)
    )

    update = _Update()
    asyncio.run(handlers_core.cmd_digest(update, _ctx(["on"])))
    assert calls == [True]
    assert "ativado" in update.message.sent[-1]["text"]

    update2 = _Update()
    asyncio.run(handlers_core.cmd_digest(update2, _ctx(["off"])))
    assert calls == [True, False]
    assert "desativado" in update2.message.sent[-1]["text"]


def test_cmd_digest_days_invalid_value_shows_error(monkeypatch):
    _patch_user(monkeypatch, handlers_core)
    pref = types.SimpleNamespace(weekly_digest_enabled=True)
    monkeypatch.setattr(handlers_core, "get_or_create_digest_preference", lambda *_: pref)
    monkeypatch.setattr(
        handlers_core,
        "update_weekly_digest_preferences",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not be called")),
    )

    update = _Update()
    asyncio.run(handlers_core.cmd_digest(update, _ctx(["days", "abc"])))
    assert "inválido" in update.message.sent[-1]["text"].lower()


def test_cmd_digest_days_missing_value_shows_usage(monkeypatch):
    _patch_user(monkeypatch, handlers_core)
    pref = types.SimpleNamespace(weekly_digest_enabled=True)
    monkeypatch.setattr(handlers_core, "get_or_create_digest_preference", lambda *_: pref)

    update = _Update()
    asyncio.run(handlers_core.cmd_digest(update, _ctx(["days"])))
    assert "Uso:" in update.message.sent[-1]["text"]


def test_cmd_alertas_renders_daily_limit(monkeypatch):
    _patch_user(monkeypatch, handlers)
    monkeypatch.setattr(handlers, "get_daily_limit_for_user", lambda *_: 15)
    update = _Update()
    asyncio.run(handlers.cmd_alertas(update, _ctx()))

    text = update.message.sent[-1]["text"]
    assert "15 alertas/dia" in text


def test_cmd_buscar_without_query_shows_usage(monkeypatch):
    async def _no_guard(*_a, **_k):
        return False

    monkeypatch.setattr(handlers, "maybe_guard_active_session_command", _no_guard)
    update = _Update()
    asyncio.run(handlers.cmd_buscar(update, _ctx()))

    text = update.message.sent[-1]["text"]
    assert "/buscar" in text


def test_cmd_wishlist_listar_renders_summaries(monkeypatch):
    _patch_user(monkeypatch, handlers)
    monkeypatch.setattr(handlers, "get_wishlist_summaries", lambda *_: ["summary-1"])
    rendered = {}

    def _render(summaries):
        rendered["summaries"] = summaries
        return "rendered-wishlists"

    monkeypatch.setattr(handlers, "render_user_wishlists", _render)
    update = _Update()
    asyncio.run(handlers.cmd_wishlist(update, _ctx()))

    assert update.message.sent[-1]["text"] == "rendered-wishlists"
    assert rendered["summaries"] == ["summary-1"]


def test_cmd_wishlist_rm_invalid_index_reports_error(monkeypatch):
    _patch_user(monkeypatch, handlers)
    monkeypatch.setattr(handlers, "remove_wishlist", lambda db, uid, idx: (False, "Número inválido. Use /wishlist listar."))
    update = _Update()
    asyncio.run(handlers.cmd_wishlist(update, _ctx(["rm", "9"])))

    assert "inválido" in update.message.sent[-1]["text"].lower()


def test_cmd_wishlist_rm_non_numeric_shows_usage(monkeypatch):
    _patch_user(monkeypatch, handlers)
    update = _Update()
    asyncio.run(handlers.cmd_wishlist(update, _ctx(["rm", "abc"])))

    assert "/wishlist rm" in update.message.sent[-1]["text"]
