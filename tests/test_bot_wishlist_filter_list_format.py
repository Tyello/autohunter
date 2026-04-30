from __future__ import annotations

import asyncio
import types
from app.bot import handlers_wishlist_ui


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


def test_filter_list_formats_mileage_friendly(monkeypatch):
    monkeypatch.setattr(handlers_wishlist_ui, "SessionLocal", lambda: _Session())
    monkeypatch.setattr(
        handlers_wishlist_ui,
        "get_or_create_user_by_chat",
        lambda _db, _chat_id, _username: types.SimpleNamespace(id="u1"),
    )
    monkeypatch.setattr(
        handlers_wishlist_ui,
        "list_wishlists",
        lambda _db, _uid: [types.SimpleNamespace(id="w1", query="civic")],
    )
    monkeypatch.setattr(
        handlers_wishlist_ui,
        "list_filters",
        lambda _db, _wid: [
            types.SimpleNamespace(field="mileage_km", operator="lte", value="80000"),
            types.SimpleNamespace(field="mileage_km", operator="gte", value="30000"),
            types.SimpleNamespace(field="mileage_km", operator="between", value="30000,90000"),
        ],
    )

    update = _Update()
    context = types.SimpleNamespace(args=["1"])
    asyncio.run(handlers_wishlist_ui.cmd_wishlist_filter_list(update, context))

    txt = update.message.sent[-1]
    assert "Quilometragem até 80.000 km" in txt
    assert "Quilometragem a partir de 30.000 km" in txt
    assert "Quilometragem entre 30.000 e 90.000 km" in txt


def test_filter_list_formats_seller_type_friendly(monkeypatch):
    monkeypatch.setattr(handlers_wishlist_ui, "SessionLocal", lambda: _Session())
    monkeypatch.setattr(
        handlers_wishlist_ui,
        "get_or_create_user_by_chat",
        lambda _db, _chat_id, _username: types.SimpleNamespace(id="u1"),
    )
    monkeypatch.setattr(
        handlers_wishlist_ui,
        "list_wishlists",
        lambda _db, _uid: [types.SimpleNamespace(id="w1", query="civic")],
    )
    monkeypatch.setattr(
        handlers_wishlist_ui,
        "list_filters",
        lambda _db, _wid: [
            types.SimpleNamespace(field="seller_type", operator="eq", value="private"),
            types.SimpleNamespace(field="seller_type", operator="eq", value="dealer"),
            types.SimpleNamespace(field="seller_type", operator="neq", value="dealer"),
        ],
    )

    update = _Update()
    context = types.SimpleNamespace(args=["1"])
    asyncio.run(handlers_wishlist_ui.cmd_wishlist_filter_list(update, context))

    txt = update.message.sent[-1]
    assert "Vendedor: particular" in txt
    assert "Vendedor: loja/revenda" in txt
    assert "Excluir vendedor: loja/revenda" in txt


def test_filter_list_formats_body_type_friendly(monkeypatch):
    monkeypatch.setattr(handlers_wishlist_ui, "SessionLocal", lambda: _Session())
    monkeypatch.setattr(
        handlers_wishlist_ui,
        "get_or_create_user_by_chat",
        lambda _db, _chat_id, _username: types.SimpleNamespace(id="u1"),
    )
    monkeypatch.setattr(
        handlers_wishlist_ui,
        "list_wishlists",
        lambda _db, _uid: [types.SimpleNamespace(id="w1", query="civic")],
    )
    monkeypatch.setattr(
        handlers_wishlist_ui,
        "list_filters",
        lambda _db, _wid: [
            types.SimpleNamespace(field="body_type", operator="eq", value="hatch"),
            types.SimpleNamespace(field="body_type", operator="eq", value="suv"),
            types.SimpleNamespace(field="body_type", operator="neq", value="pickup"),
            types.SimpleNamespace(field="body_type", operator="eq", value="convertible"),
        ],
    )

    update = _Update()
    context = types.SimpleNamespace(args=["1"])
    asyncio.run(handlers_wishlist_ui.cmd_wishlist_filter_list(update, context))

    txt = update.message.sent[-1]
    assert "Carroceria: hatch" in txt
    assert "Carroceria: SUV" in txt
    assert "Excluir carroceria: pickup" in txt
    assert "Carroceria: conversível" in txt


def test_filter_list_formats_doors_friendly(monkeypatch):
    monkeypatch.setattr(handlers_wishlist_ui, "SessionLocal", lambda: _Session())
    monkeypatch.setattr(
        handlers_wishlist_ui,
        "get_or_create_user_by_chat",
        lambda _db, _chat_id, _username: types.SimpleNamespace(id="u1"),
    )
    monkeypatch.setattr(
        handlers_wishlist_ui,
        "list_wishlists",
        lambda _db, _uid: [types.SimpleNamespace(id="w1", query="civic")],
    )
    monkeypatch.setattr(
        handlers_wishlist_ui,
        "list_filters",
        lambda _db, _wid: [
            types.SimpleNamespace(field="doors", operator="eq", value="4"),
            types.SimpleNamespace(field="doors", operator="neq", value="2"),
            types.SimpleNamespace(field="doors", operator="lte", value="4"),
            types.SimpleNamespace(field="doors", operator="gte", value="4"),
            types.SimpleNamespace(field="doors", operator="between", value="2,4"),
        ],
    )

    update = _Update()
    context = types.SimpleNamespace(args=["1"])
    asyncio.run(handlers_wishlist_ui.cmd_wishlist_filter_list(update, context))

    txt = update.message.sent[-1]
    assert "Portas: 4" in txt
    assert "Excluir portas: 2" in txt
    assert "Portas até 4" in txt
    assert "Portas a partir de 4" in txt
    assert "Portas entre 2 e 4" in txt
