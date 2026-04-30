from __future__ import annotations

import uuid

from app.models.user import User
from app.models.wishlist import Wishlist
from app.services.wishlists_service import add_filter, list_filters


def _mk_wishlist(db):
    user = User(id=uuid.uuid4(), telegram_chat_id=5410200000 + (uuid.uuid4().int % 100000), username="doors", is_active=True)
    db.add(user)
    db.commit()
    wl = Wishlist(user_id=user.id, query="civic", is_active=True)
    db.add(wl)
    db.commit()
    return wl


def test_add_filter_accepts_doors_field_aliases(db):
    aliases = ["portas", "porta", "qtd_portas", "quantidade_portas", "doors"]
    for field in aliases:
        wl = _mk_wishlist(db)
        ok, _ = add_filter(db, wl.id, field, "apenas", "4 portas")
        assert ok is True
        f = list_filters(db, wl.id)[0]
        assert f.field == "doors"
        assert f.operator == "eq"
        assert f.value == "4"


def test_add_filter_accepts_doors_operators_and_between(db):
    wl = _mk_wishlist(db)
    assert add_filter(db, wl.id, "portas", "excluir", "2p")[0] is True
    assert add_filter(db, wl.id, "portas", ">=", "4")[0] is True
    assert add_filter(db, wl.id, "portas", "entre", "2 4")[0] is True

    fs = list_filters(db, wl.id)
    assert (fs[0].field, fs[0].operator, fs[0].value) == ("doors", "neq", "2")
    assert (fs[1].field, fs[1].operator, fs[1].value) == ("doors", "gte", "4")
    assert (fs[2].field, fs[2].operator, fs[2].value) == ("doors", "between", "2,4")


def test_add_filter_rejects_invalid_doors_value_range_and_duplicate(db):
    wl = _mk_wishlist(db)
    ok, msg = add_filter(db, wl.id, "doors", "eq", "abc")
    assert ok is False and "Portas inválido" in msg

    ok, msg = add_filter(db, wl.id, "doors", "eq", "0")
    assert ok is False and "Portas inválido" in msg

    ok, msg = add_filter(db, wl.id, "doors", "eq", "7")
    assert ok is False and "Portas inválido" in msg

    ok, _ = add_filter(db, wl.id, "portas", "=", "4")
    assert ok is True
    ok2, msg2 = add_filter(db, wl.id, "doors", "igual", "4 portas")
    assert ok2 is False
    assert "duplicado" in msg2.lower()
