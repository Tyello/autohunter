import uuid

from app.models.user import User
from app.models.wishlist import Wishlist
from app.services.wishlists_service import add_filter, list_filters


def _mk_wl(db, username: str):
    user = User(id=uuid.uuid4(), telegram_chat_id=5410288800 + (uuid.uuid4().int % 1000000), username=username, is_active=True)
    db.add(user)
    db.commit()
    wl = Wishlist(user_id=user.id, query="civic", is_active=True)
    db.add(wl)
    db.commit()
    return wl


def test_body_type_field_aliases_and_operator_aliases(db):
    aliases = ["carroceria", "tipo_carroceria", "categoria", "body_type"]
    for i, field in enumerate(aliases):
        wl = _mk_wl(db, f"body-{i}")
        ok, msg = add_filter(db, wl.id, field, "apenas", "hatchback")
        assert ok is True, msg
        f = list_filters(db, wl.id)[0]
        assert f.field == "body_type"
        assert f.operator == "eq"
        assert f.value == "hatch"


def test_body_type_value_aliases_store_canonical(db):
    values = [
        ("sedã", "sedan"),
        ("utilitário esportivo", "suv"),
        ("picape", "pickup"),
        ("caminhonete", "pickup"),
        ("coupé", "coupe"),
        ("conversível", "convertible"),
        ("perua", "wagon"),
        ("station wagon", "wagon"),
    ]
    for i, (raw, expected) in enumerate(values):
        wl = _mk_wl(db, f"body-values-{i}")
        ok, msg = add_filter(db, wl.id, "tipo", "eq", raw)
        assert ok is True, msg
        f = list_filters(db, wl.id)[0]
        assert f.value == expected


def test_body_type_neq_alias_and_duplicate_block(db):
    wl = _mk_wl(db, "body-dup")
    ok, msg = add_filter(db, wl.id, "estilo", "excluir", "pickup")
    assert ok is True, msg
    ok2, msg2 = add_filter(db, wl.id, "body", "diferente", "caminhonete")
    assert ok2 is False
    assert "duplicado" in msg2.lower()


def test_body_type_invalid_value_error(db):
    wl = _mk_wl(db, "body-invalid")
    ok, msg = add_filter(db, wl.id, "carroceria", "=", "spaceship")
    assert ok is False
    assert "Valor inválido para body_type" in msg
