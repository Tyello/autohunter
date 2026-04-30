import uuid

from app.models.user import User
from app.models.wishlist import Wishlist
from app.services.wishlists_service import add_filter, list_filters


def _mk_wl(db, username: str):
    user = User(id=uuid.uuid4(), telegram_chat_id=5410188800 + (uuid.uuid4().int % 1000000), username=username, is_active=True)
    db.add(user)
    db.commit()
    wl = Wishlist(user_id=user.id, query="civic", is_active=True)
    db.add(wl)
    db.commit()
    return wl


def test_seller_type_field_aliases_and_value_aliases(db):
    aliases = ["seller", "vendedor", "tipo_vendedor", "anunciante"]
    for i, field in enumerate(aliases):
        wl = _mk_wl(db, f"seller-{i}")
        ok, msg = add_filter(db, wl.id, field, "apenas", "pessoa física")
        assert ok is True, msg
        f = list_filters(db, wl.id)[0]
        assert f.field == "seller_type"
        assert f.operator == "eq"
        assert f.value == "private"


def test_seller_type_value_aliases_store_canonical(db):
    wl = _mk_wl(db, "seller-value")
    ok, msg = add_filter(db, wl.id, "vendedor", "somente", "concessionária")
    assert ok is True, msg
    f = list_filters(db, wl.id)[0]
    assert f.value == "dealer"


def test_seller_type_neq_alias_and_duplicate_block(db):
    wl = _mk_wl(db, "seller-dup")
    ok, msg = add_filter(db, wl.id, "vendedor", "excluir", "revenda")
    assert ok is True, msg
    ok2, msg2 = add_filter(db, wl.id, "seller_type", "diferente", "loja")
    assert ok2 is False
    assert "duplicado" in msg2.lower()


def test_seller_type_invalid_value_error(db):
    wl = _mk_wl(db, "seller-invalid")
    ok, msg = add_filter(db, wl.id, "vendedor", "eq", "importadora")
    assert ok is False
    assert "Valor inválido para seller_type" in msg
