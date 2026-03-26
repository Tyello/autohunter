from __future__ import annotations

import uuid

from app.models.user import User
from app.models.wishlist import Wishlist
from app.services.wishlists_service import add_filter, add_wishlist, list_filters


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
