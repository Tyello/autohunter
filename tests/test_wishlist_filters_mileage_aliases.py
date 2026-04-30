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
