from __future__ import annotations

import uuid

from app.models.car_listing import CarListing
from app.models.user import User
from app.services.wishlists_service import add_wishlist
from app.services.wishlist_tracking_service import add_tracked_listing, list_tracked_listings, remove_tracked_listing


def _mk_user(db, chat_id=1001):
    u = User(id=uuid.uuid4(), telegram_chat_id=chat_id, username=f"u{chat_id}", is_active=True)
    db.add(u)
    db.commit()
    return u


def _mk_listing(db, i: int):
    l = CarListing(
        id=uuid.uuid4(),
        source="olx",
        external_id=f"EXT{i}",
        title=f"Civic {i}",
        url=f"https://example.com/{i}",
        price=100000 + i,
        location="São Paulo, SP",
        currency="BRL",
        extras={},
    )
    db.add(l)
    db.commit()
    return l


def test_tracking_add_duplicate_limit_list_remove(db, monkeypatch):
    user = _mk_user(db)
    monkeypatch.setattr("app.services.wishlists_service.trigger_initial_run_for_wishlist", lambda *_args, **_kwargs: {"triggered": 0})
    ok, _ = add_wishlist(db, user.id, "civic")
    assert ok is True

    l1 = _mk_listing(db, 1)
    l2 = _mk_listing(db, 2)
    l3 = _mk_listing(db, 3)
    l4 = _mk_listing(db, 4)

    ok, msg = add_tracked_listing(db, user_id=user.id, wishlist_index=1, listing_ref=l1.external_id)
    assert ok is True
    assert "slot 1/3" in msg

    ok, msg = add_tracked_listing(db, user_id=user.id, wishlist_index=1, listing_ref=l1.external_id)
    assert ok is False
    assert "já está rastreado" in msg

    assert add_tracked_listing(db, user_id=user.id, wishlist_index=1, listing_ref=l2.external_id)[0] is True
    assert add_tracked_listing(db, user_id=user.id, wishlist_index=1, listing_ref=l3.external_id)[0] is True

    ok, msg = add_tracked_listing(db, user_id=user.id, wishlist_index=1, listing_ref=l4.external_id)
    assert ok is False
    assert "Limite atingido" in msg

    ok, msg = list_tracked_listings(db, user_id=user.id, wishlist_index=1)
    assert ok is True
    assert "1. Civic 1" in msg
    assert "3. Civic 3" in msg

    ok, msg = remove_tracked_listing(db, user_id=user.id, wishlist_index=1, slot=2)
    assert ok is True
    assert "removido" in msg.lower()


def test_tracking_validates_wishlist_ownership_and_eligibility(db, monkeypatch):
    user1 = _mk_user(db, 2001)
    user2 = _mk_user(db, 2002)
    monkeypatch.setattr("app.services.wishlists_service.trigger_initial_run_for_wishlist", lambda *_args, **_kwargs: {"triggered": 0})
    add_wishlist(db, user1.id, "fusca")

    ok, msg = add_tracked_listing(db, user_id=user2.id, wishlist_index=1, listing_ref="EXT404")
    assert ok is False
    assert "não existe" in msg.lower()

    ok, msg = add_tracked_listing(db, user_id=user1.id, wishlist_index=1, listing_ref="EXT404")
    assert ok is False
    assert "não elegível" in msg


def test_tracking_add_accepts_url_with_query_fragment(db, monkeypatch):
    user = _mk_user(db, 3001)
    monkeypatch.setattr("app.services.wishlists_service.trigger_initial_run_for_wishlist", lambda *_args, **_kwargs: {"triggered": 0})
    add_wishlist(db, user.id, "civic")

    listing = _mk_listing(db, 30)

    ok, msg = add_tracked_listing(
        db,
        user_id=user.id,
        wishlist_index=1,
        listing_ref=f"{listing.url}?utm_source=x#frag",
    )
    assert ok is True, msg
