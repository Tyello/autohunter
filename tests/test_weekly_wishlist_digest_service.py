from __future__ import annotations

from datetime import datetime, timedelta, timezone
import uuid

from app.models.car_listing import CarListing
from app.models.user import User
from app.models.wishlist import Wishlist
from app.models.wishlist_listing_activity import WishlistListingActivity
from app.services.weekly_wishlist_digest_service import WeeklyWishlistDigestService


def _mk_user(db, chat_id: int = 999) -> User:
    user = User(id=uuid.uuid4(), telegram_chat_id=chat_id, username="u", is_active=True)
    db.add(user)
    db.commit()
    return user


def _mk_wishlist(db, user: User, query: str) -> Wishlist:
    wl = Wishlist(user_id=user.id, query=query, is_active=True)
    db.add(wl)
    db.commit()
    return wl


def _mk_listing(db, idx: int, *, sold: bool = False) -> CarListing:
    listing = CarListing(
        source="olx",
        external_id=f"E{idx}",
        title=f"Carro {idx}",
        url=f"https://example/{idx}",
        price=10000 + idx,
        location="SP",
        is_sold=sold,
    )
    db.add(listing)
    db.commit()
    return listing


def _mk_activity(db, wishlist: Wishlist, listing: CarListing, *, minutes_ago: int, status: str = "active") -> None:
    now = datetime.now(timezone.utc)
    row = WishlistListingActivity(
        wishlist_id=wishlist.id,
        car_listing_id=listing.id,
        listing_identity_key=f"{listing.source}:{listing.external_id}:{wishlist.id}",
        source_name=listing.source,
        source_listing_id=listing.external_id,
        listing_url=listing.url,
        status=status,
        first_seen_at=now - timedelta(days=1),
        last_seen_at=now - timedelta(minutes=minutes_ago),
        missing_runs_count=0,
    )
    db.add(row)
    db.commit()


def test_weekly_digest_user_with_three_plus_active(db):
    user = _mk_user(db, 111)
    wl = _mk_wishlist(db, user, "civic")
    l1 = _mk_listing(db, 1)
    l2 = _mk_listing(db, 2)
    l3 = _mk_listing(db, 3)
    l4 = _mk_listing(db, 4)
    _mk_activity(db, wl, l1, minutes_ago=50)
    _mk_activity(db, wl, l2, minutes_ago=40)
    _mk_activity(db, wl, l3, minutes_ago=30)
    _mk_activity(db, wl, l4, minutes_ago=20)

    digest = WeeklyWishlistDigestService(db).build_all_digests()[0]
    item = digest.wishlists[0]

    assert item.total_active == 4
    assert len(item.latest_listings) == 3
    assert [x.url for x in item.latest_listings] == [l4.url, l3.url, l2.url]


def test_weekly_digest_with_less_than_three_and_zero_active(db):
    user = _mk_user(db, 112)
    wl_a = _mk_wishlist(db, user, "jetta")
    wl_b = _mk_wishlist(db, user, "fusca")

    l1 = _mk_listing(db, 10)
    l2 = _mk_listing(db, 11)
    _mk_activity(db, wl_a, l1, minutes_ago=10)
    _mk_activity(db, wl_a, l2, minutes_ago=5)

    # inactive + sold must not appear in digest totals
    sold = _mk_listing(db, 12, sold=True)
    inactive = _mk_listing(db, 13)
    _mk_activity(db, wl_b, sold, minutes_ago=2)
    _mk_activity(db, wl_b, inactive, minutes_ago=1, status="inactive")

    digest = WeeklyWishlistDigestService(db).build_all_digests()[0]
    by_query = {w.query: w for w in digest.wishlists}

    assert by_query["jetta"].total_active == 2
    assert len(by_query["jetta"].latest_listings) == 2

    assert by_query["fusca"].total_active == 0
    assert by_query["fusca"].latest_listings == []


def test_weekly_digest_multiple_wishlists_same_user(db):
    user = _mk_user(db, 113)
    wl1 = _mk_wishlist(db, user, "civic si")
    wl2 = _mk_wishlist(db, user, "up tsi")

    l1 = _mk_listing(db, 21)
    l2 = _mk_listing(db, 22)
    _mk_activity(db, wl1, l1, minutes_ago=5)
    _mk_activity(db, wl2, l2, minutes_ago=3)

    digest = WeeklyWishlistDigestService(db).build_all_digests()[0]
    assert len(digest.wishlists) == 2
    assert sum(w.total_active for w in digest.wishlists) == 2
