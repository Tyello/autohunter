from __future__ import annotations

import asyncio
import types

from app.bot import handlers


class _Message:
    def __init__(self):
        self.sent: list[str] = []

    async def reply_text(self, text, reply_markup=None):
        self.sent.append(text)


class _Update:
    def __init__(self):
        self.effective_chat = types.SimpleNamespace(id=111)
        self.effective_user = types.SimpleNamespace(username="tester")
        self.message = _Message()
        self.effective_message = self.message


class _Session:
    def __enter__(self):
        return self

    def __exit__(self, *_):
        return None


def _patch_base(monkeypatch):
    monkeypatch.setattr(handlers, "SessionLocal", lambda: _Session())
    monkeypatch.setattr(
        handlers,
        "get_or_create_user_by_chat",
        lambda _db, _chat_id, _username: types.SimpleNamespace(id="u1"),
    )
    monkeypatch.setattr(
        handlers,
        "list_wishlists",
        lambda _db, _uid: [types.SimpleNamespace(id="w1", query="civic")],
    )


def test_wishlist_filter_add_legacy_join_value_for_between(monkeypatch):
    _patch_base(monkeypatch)
    captured = {}

    def _add_filter(_db, _wid, field, op, value):
        captured["args"] = (field, op, value)
        return True, "ok"

    monkeypatch.setattr(handlers, "add_filter", _add_filter)

    update = _Update()
    context = types.SimpleNamespace(args=["filter", "add", "1", "km", "between", "30000", "90000"])
    asyncio.run(handlers.cmd_wishlist(update, context))

    assert captured["args"] == ("km", "between", "30000 90000")


def test_wishlist_filter_add_legacy_simple_value_still_works(monkeypatch):
    _patch_base(monkeypatch)
    captured = {}

    def _add_filter(_db, _wid, field, op, value):
        captured["args"] = (field, op, value)
        return True, "ok"

    monkeypatch.setattr(handlers, "add_filter", _add_filter)

    update = _Update()
    context = types.SimpleNamespace(args=["filter", "add", "1", "source", "eq", "olx"])
    asyncio.run(handlers.cmd_wishlist(update, context))

    assert captured["args"] == ("source", "eq", "olx")


def test_wishlist_filter_help_contains_new_examples(monkeypatch):
    _patch_base(monkeypatch)

    update = _Update()
    context = types.SimpleNamespace(args=["filter"])
    asyncio.run(handlers.cmd_wishlist(update, context))

    msg = update.message.sent[-1]
    assert "/wishlist filter add 1 km lte 90000" in msg
    assert "/wishlist filter add 1 km between 30000 90000" in msg
    assert "/wishlist filter add 1 portas eq 2" in msg
    assert "/wishlist filter add 1 carroceria eq sedan" in msg
    assert "/wishlist filter add 1 vendedor eq particular" in msg


def test_wishlist_filter_list_renders_friendly_field_names(monkeypatch):
    _patch_base(monkeypatch)
    monkeypatch.setattr(
        handlers,
        "list_filters",
        lambda _db, _wid: [
            types.SimpleNamespace(field="mileage_km", operator="lte", value="90000"),
            types.SimpleNamespace(field="seller_type", operator="eq", value="private"),
            types.SimpleNamespace(field="body_type", operator="eq", value="sedan"),
            types.SimpleNamespace(field="doors", operator="eq", value="2"),
        ],
    )

    update = _Update()
    context = types.SimpleNamespace(args=["filter", "list", "1"])
    asyncio.run(handlers.cmd_wishlist(update, context))

    msg = update.message.sent[-1]
    assert "1. km lte 90000" in msg
    assert "2. vendedor eq private" in msg
    assert "3. carroceria eq sedan" in msg
    assert "4. portas eq 2" in msg
