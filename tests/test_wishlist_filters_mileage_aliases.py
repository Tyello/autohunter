import uuid

from app.models.user import User
from app.models.wishlist import Wishlist
from app.services.wishlists_service import add_filter, list_filters


def test_add_filter_accepts_mileage_aliases_and_operator_aliases(db):
    user = User(id=uuid.uuid4(), telegram_chat_id=5410199999, username="km-alias", is_active=True)
    db.add(user)
    db.commit()
    wl = Wishlist(user_id=user.id, query="civic", is_active=True)
    db.add(wl)
    db.commit()
    ok, msg = add_filter(db, wl.id, "quilometragem", "até", "90.000 km")
    assert ok is True, msg

    fs = list_filters(db, wl.id)
    assert len(fs) == 1
    assert fs[0].field == "mileage_km"
    assert fs[0].operator == "lte"
    assert fs[0].value == "90000"


def test_mileage_aliases_normalization_and_duplicates(db):
    user = User(id=uuid.uuid4(), telegram_chat_id=5410199911, username="km-dup", is_active=True)
    db.add(user)
    db.commit()
    wl = Wishlist(user_id=user.id, query="civic", is_active=True)
    db.add(wl)
    db.commit()

    ok, msg = add_filter(db, wl.id, "km", "<=", "80.000 km")
    assert ok is True, msg
    ok2, msg2 = add_filter(db, wl.id, "quilometragem", "até", "80000")
    assert ok2 is False
    assert "duplicado" in msg2.lower()


def test_mileage_between_alias_entre(db):
    user = User(id=uuid.uuid4(), telegram_chat_id=5410199922, username="km-between", is_active=True)
    db.add(user)
    db.commit()
    wl = Wishlist(user_id=user.id, query="civic", is_active=True)
    db.add(wl)
    db.commit()

    ok, msg = add_filter(db, wl.id, "quilometragem", "entre", "30.000 90.000")
    assert ok is True, msg
    fs = list_filters(db, wl.id)
    assert fs[0].field == "mileage_km"
    assert fs[0].operator == "between"
    assert fs[0].value == "30000,90000"


def test_mileage_validation_errors(db):
    user = User(id=uuid.uuid4(), telegram_chat_id=5410199933, username="km-invalid", is_active=True)
    db.add(user)
    db.commit()
    wl = Wishlist(user_id=user.id, query="civic", is_active=True)
    db.add(wl)
    db.commit()

    ok, msg = add_filter(db, wl.id, "km", "<=", "abc")
    assert ok is False and "Quilometragem inválida" in msg

    ok, msg = add_filter(db, wl.id, "km", "<=", "-1")
    assert ok is False and "fora do intervalo" in msg

    ok, msg = add_filter(db, wl.id, "km", "<=", "1500001")
    assert ok is False and "fora do intervalo" in msg
