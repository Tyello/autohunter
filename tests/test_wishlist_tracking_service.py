from __future__ import annotations

import uuid

from app.models.car_listing import CarListing
from app.models.user import User
from app.models.wishlist import Wishlist
from app.models.wishlist_tracked_listing import WishlistTrackedListing
from app.services.wishlists_service import add_wishlist
from app.services.wishlist_tracking_service import add_tracked_listing, add_tracked_listing_result, list_tracked_listings, remove_tracked_listing


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
    monkeypatch.setattr("app.services.wishlist_tracking_service.get_user_plan_snapshot", lambda *_args, **_kwargs: {"plan_code": "premium"})
    ok, _ = add_wishlist(db, user.id, "civic")
    assert ok is True

    l1 = _mk_listing(db, 1)
    l2 = _mk_listing(db, 2)
    l3 = _mk_listing(db, 3)
    l4 = _mk_listing(db, 4)

    ok, msg = add_tracked_listing(db, user_id=user.id, wishlist_index=1, listing_ref=l1.external_id)
    assert ok is True
    assert "Anúncio rastreado" in msg

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
    assert "Slot 1" in msg
    assert "Slot 2" in msg
    assert "Slot 3" in msg
    assert "Preço atual:" in msg
    assert "Preço inicial:" in msg
    assert "Notificações automáticas:" in msg

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
    assert "não encontrada" in msg.lower()

    ok, msg = add_tracked_listing(db, user_id=user1.id, wishlist_index=1, listing_ref="EXT404")
    assert ok is False
    assert "não encontrei" in msg.lower()


def test_tracking_list_handles_orphan_listing_row(db, monkeypatch):
    user = _mk_user(db, 3001)
    monkeypatch.setattr("app.services.wishlists_service.trigger_initial_run_for_wishlist", lambda *_args, **_kwargs: {"triggered": 0})
    ok, _ = add_wishlist(db, user.id, "civic")
    assert ok is True

    wishlist = db.query(Wishlist).filter(Wishlist.user_id == user.id).one()
    tracked = WishlistTrackedListing(wishlist_id=wishlist.id, car_listing_id=None, slot=1)
    db.add(tracked)
    db.commit()

    ok, msg = list_tracked_listings(db, user_id=user.id, wishlist_index=1)
    assert ok is True
    assert "indisponível" in msg.lower()


def test_tracking_add_saves_initial_snapshot(db, monkeypatch):
    user = _mk_user(db, 4001)
    monkeypatch.setattr("app.services.wishlists_service.trigger_initial_run_for_wishlist", lambda *_args, **_kwargs: {"triggered": 0})
    ok, _ = add_wishlist(db, user.id, "civic")
    assert ok is True
    listing = _mk_listing(db, 10)

    ok, _ = add_tracked_listing(db, user_id=user.id, wishlist_index=1, listing_ref=listing.external_id)
    assert ok is True
    row = db.query(WishlistTrackedListing).filter(WishlistTrackedListing.wishlist_id.isnot(None)).one()
    assert row.initial_price == listing.price
    assert row.last_observed_price == listing.price


def test_tracking_add_result_statuses(db, monkeypatch):
    user = _mk_user(db, 5001)
    monkeypatch.setattr("app.services.wishlists_service.trigger_initial_run_for_wishlist", lambda *_args, **_kwargs: {"triggered": 0})
    monkeypatch.setattr("app.services.wishlist_tracking_service.get_user_plan_snapshot", lambda *_args, **_kwargs: {"plan_code": "premium"})
    ok, _ = add_wishlist(db, user.id, "gol")
    assert ok is True
    l1 = _mk_listing(db, 21)
    l2 = _mk_listing(db, 22)
    l3 = _mk_listing(db, 23)
    l4 = _mk_listing(db, 24)

    r1 = add_tracked_listing_result(db, user_id=user.id, wishlist_index=1, listing_ref=l1.external_id)
    assert r1.status == "added"
    assert r1.ok is True
    assert r1.slot == 1

    r2 = add_tracked_listing_result(db, user_id=user.id, wishlist_index=1, listing_ref=l1.external_id)
    assert r2.status == "already_tracked"

    assert add_tracked_listing_result(db, user_id=user.id, wishlist_index=1, listing_ref=l2.external_id).status == "added"
    assert add_tracked_listing_result(db, user_id=user.id, wishlist_index=1, listing_ref=l3.external_id).status == "added"
    r3 = add_tracked_listing_result(db, user_id=user.id, wishlist_index=1, listing_ref=l4.external_id)
    assert r3.status == "slots_full"

    r4 = add_tracked_listing_result(db, user_id=user.id, wishlist_index=2, listing_ref=l4.external_id)
    assert r4.status == "wishlist_not_found"

    r5 = add_tracked_listing_result(db, user_id=user.id, wishlist_index=1, listing_ref="EXT404")
    assert r5.status == "listing_not_found"


def test_tracking_add_result_automation_enabled_free_and_premium(db, monkeypatch):
    monkeypatch.setattr("app.services.wishlists_service.trigger_initial_run_for_wishlist", lambda *_args, **_kwargs: {"triggered": 0})
    user_free = _mk_user(db, 6001)
    user_premium = _mk_user(db, 6002)
    add_wishlist(db, user_free.id, "uno")
    add_wishlist(db, user_premium.id, "palio")
    lf = _mk_listing(db, 31)
    lp = _mk_listing(db, 32)

    monkeypatch.setattr("app.services.wishlist_tracking_service.get_user_plan_snapshot", lambda _db, uid: {"plan_code": "premium"} if str(uid) == str(user_premium.id) else {"plan_code": "free"})

    rf = add_tracked_listing_result(db, user_id=user_free.id, wishlist_index=1, listing_ref=lf.external_id)
    rp = add_tracked_listing_result(db, user_id=user_premium.id, wishlist_index=1, listing_ref=lp.external_id)
    assert rf.automation_enabled is False
    assert rp.automation_enabled is True
