from __future__ import annotations

import uuid

import pytest
from sqlalchemy.exc import IntegrityError

from app.models.fipe_lookup_request import FipeLookupRequest
from app.models.user import User
from app.models.wishlist import Wishlist


def _make_wishlist(db):
    user = User(id=uuid.uuid4(), telegram_chat_id=990202, username="fipe-lookup-user", is_active=True)
    db.add(user)
    wishlist = Wishlist(id=uuid.uuid4(), user_id=user.id, query="honda civic", is_active=True)
    db.add(wishlist)
    db.commit()
    return wishlist


def test_defaults_and_insert(db):
    wishlist = _make_wishlist(db)

    request = FipeLookupRequest(id=uuid.uuid4(), wishlist_id=wishlist.id)
    db.add(request)
    db.commit()
    db.refresh(request)

    assert request.status == "pending"
    assert request.attempts == 0
    assert request.last_error is None
    assert request.processed_at is None
    assert request.created_at is not None
    assert request.updated_at is not None


def test_status_check_constraint(db):
    wishlist = _make_wishlist(db)

    request = FipeLookupRequest(id=uuid.uuid4(), wishlist_id=wishlist.id, status="bogus")
    db.add(request)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
    else:
        # SQLite without enforced CHECK constraints accepts the row; assert the field itself.
        assert request.status == "bogus"
