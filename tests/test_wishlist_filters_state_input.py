from __future__ import annotations

import uuid

from app.models.user import User
from app.models.wishlist import Wishlist
from app.services.wishlists_service import add_filter, add_wishlist, list_filters, normalize_wishlist_filter_input, parse_wishlist_filter_expression, parse_wishlist_query_with_implicit_filters


def test_add_filter_state_accepts_state_name(db, monkeypatch):
    user = User(id=uuid.uuid4(), telegram_chat_id=4444, username="state-user", is_active=True)
    db.add(user)
    db.commit()

    monkeypatch.setattr("app.services.wishlists_service.trigger_initial_run_for_wishlist", lambda *_args, **_kwargs: {"triggered": 0})

    ok, _ = add_wishlist(db, user.id, "civic")
    assert ok is True
    wl = db.query(Wishlist).filter_by(user_id=user.id).first()

    ok, msg = add_filter(db, wl.id, "state", "eq", "São Paulo")
    assert ok is True, msg

    fs = list_filters(db, wl.id)
    assert any(f.field == "state" and f.value == "SP" for f in fs)


def test_normalize_wishlist_filter_input_state_alias_without_db():
    normalized = normalize_wishlist_filter_input("state", "igual", "São Paulo")
    assert normalized.field == "state"
    assert normalized.operator == "eq"
    assert normalized.value == "SP"


def test_parse_filter_expression_and_price_canonicalization():
    price = parse_wishlist_filter_expression("price", "até 150.000")
    assert price[0].operator == "lte"
    assert price[0].value == "150000"
    year = parse_wishlist_filter_expression("year", "entre 2017 e 2021")
    assert [(y.operator, y.value) for y in year] == [("gte", "2017"), ("lte", "2021")]
    mileage = parse_wishlist_filter_expression("mileage_km", "até 90.000 km")
    assert mileage[0].value == "90000"
    state = parse_wishlist_filter_expression("state", "São Paulo")
    assert state[0].value == "SP"


def test_parse_query_with_implicit_filters():
    parsed = parse_wishlist_query_with_implicit_filters("a5 entre 2017 e 2021")
    assert parsed.cleaned_query == "a5"
    assert [(f.field, f.operator, f.value) for f in parsed.filters] == [("year", "gte", "2017"), ("year", "lte", "2021")]
