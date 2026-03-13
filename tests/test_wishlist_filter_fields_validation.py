import uuid

from app.models.user import User
from app.models.wishlist import Wishlist
from app.services.wishlists_service import add_filter


def _mk_wishlist(db):
    u = User(id=uuid.uuid4(), telegram_chat_id=99119911, username="filters", is_active=True)
    db.add(u)
    db.commit()

    wl = Wishlist(user_id=u.id, query="civic", is_active=True)
    db.add(wl)
    db.commit()
    return wl


def test_add_filter_accepts_color_city_state(db):
    wl = _mk_wishlist(db)

    ok1, _ = add_filter(db, wl.id, "color", "eq", "prata")
    ok2, _ = add_filter(db, wl.id, "city", "eq", "São Paulo")
    ok3, _ = add_filter(db, wl.id, "state", "eq", "SP")

    assert ok1 is True
    assert ok2 is True
    assert ok3 is True


def test_add_filter_state_rejects_invalid_uf(db):
    wl = _mk_wishlist(db)

    ok_state, msg = add_filter(db, wl.id, "state", "eq", "SPO")

    assert ok_state is False
    assert "UF" in msg
