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


def test_normalize_wishlist_filter_aliases_for_color_city_state():
    assert normalize_wishlist_filter_input("cor", "equals", "vermelho").field == "color"
    assert normalize_wishlist_filter_input("cidade", "eq", "São Paulo").field == "city"
    assert normalize_wishlist_filter_input("uf", "eq", "sp").value == "SP"
    assert normalize_wishlist_filter_input("estado", "eq", "sp").value == "SP"


def test_state_rejects_invalid_operator_and_invalid_uf():
    try:
        normalize_wishlist_filter_input("state", "gte", "SP")
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "Operador inválido para state. Use: eq" in str(exc)

    try:
        normalize_wishlist_filter_input("uf", "eq", "SPO")
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "UF com 2 letras" in str(exc)


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


def test_parse_query_price_range_implicit():
    parsed = parse_wishlist_query_with_implicit_filters("civic entre 70000 e 90000")
    assert parsed.cleaned_query == "civic"
    assert [(f.field, f.operator, f.value) for f in parsed.filters] == [("price", "gte", "70000"), ("price", "lte", "90000")]


def test_parse_query_with_implicit_single_year_token():
    parsed = parse_wishlist_query_with_implicit_filters("a4 avant 2019")
    assert parsed.cleaned_query == "a4 avant"
    assert [(f.field, f.operator, f.value) for f in parsed.filters] == [("year", "gte", "2019"), ("year", "lte", "2019")]


def test_parse_query_with_numeric_models_keeps_tokens_and_extracts_year():
    parsed = parse_wishlist_query_with_implicit_filters("bmw 320i 2019")
    assert parsed.cleaned_query == "bmw 320i"
    assert [(f.field, f.operator, f.value) for f in parsed.filters] == [("year", "gte", "2019"), ("year", "lte", "2019")]

    parsed = parse_wishlist_query_with_implicit_filters("porsche 911 2021")
    assert parsed.cleaned_query == "porsche 911"
    assert [(f.field, f.operator, f.value) for f in parsed.filters] == [("year", "gte", "2021"), ("year", "lte", "2021")]

    parsed = parse_wishlist_query_with_implicit_filters("fiat 500 2017")
    assert parsed.cleaned_query == "fiat 500"
    assert [(f.field, f.operator, f.value) for f in parsed.filters] == [("year", "gte", "2017"), ("year", "lte", "2017")]


def test_parse_query_pure_model_codes_do_not_become_year_filter():
    assert parse_wishlist_query_with_implicit_filters("a4").filters == []
    assert parse_wishlist_query_with_implicit_filters("320i").filters == []
    assert parse_wishlist_query_with_implicit_filters("911").filters == []


def test_normalize_price_between_canonical():
    normalized = normalize_wishlist_filter_input("price", "between", "70.000 90.000")
    assert normalized.value == "70000,90000"


def test_parse_filter_expression_price_directional_terms():
    assert parse_wishlist_filter_expression("price", "acima de 110000")[0].operator == "gte"
    assert parse_wishlist_filter_expression("price", "acima de 110000")[0].value == "110000"
    assert parse_wishlist_filter_expression("price", "acima de R$ 110.000")[0].value == "110000"
    assert parse_wishlist_filter_expression("price", "mais de 110000")[0].operator == "gte"
    assert parse_wishlist_filter_expression("price", "a partir de 110000")[0].operator == "gte"
    assert parse_wishlist_filter_expression("price", "desde 110000")[0].operator == "gte"
    assert parse_wishlist_filter_expression("price", "maior que 110000")[0].operator == "gt"
    assert parse_wishlist_filter_expression("price", "até 110000")[0].operator == "lte"
    rng = parse_wishlist_filter_expression("price", "entre 90000 e 130000")
    assert [(f.operator, f.value) for f in rng] == [("gte", "90000"), ("lte", "130000")]
