from __future__ import annotations

import uuid

from app.models.user import User
from app.models.wishlist import Wishlist
from app.services.wishlist_tokens_service import (
    candidate_wishlist_ids_for_listing_tokens,
    rebuild_tokens_for_wishlist,
)


def test_candidate_wishlist_ids_excludes_soft_deleted_and_paused_wishlists(db):
    user = User(id=uuid.uuid4(), telegram_chat_id=990101, username="token-user", is_active=True)
    db.add(user)
    active = Wishlist(id=uuid.uuid4(), user_id=user.id, query="honda civic", is_active=True)
    deleted = Wishlist(id=uuid.uuid4(), user_id=user.id, query="honda civic", is_active=True)
    paused = Wishlist(id=uuid.uuid4(), user_id=user.id, query="honda civic", is_active=False)
    db.add_all([active, deleted, paused])
    db.commit()

    deleted.deleted_at = active.created_at
    db.add(deleted)
    for wishlist in (active, deleted, paused):
        rebuild_tokens_for_wishlist(db, wishlist)
    db.commit()

    out = candidate_wishlist_ids_for_listing_tokens(db, ["honda", "civic"], min_overlap=1)

    assert out == [active.id]
