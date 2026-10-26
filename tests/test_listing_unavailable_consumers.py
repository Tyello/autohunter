from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app.models.car_listing import CarListing
from app.models.user import User
from app.models.wishlist import Wishlist
from app.models.wishlist_listing_activity import WishlistListingActivity
from app.services.listing_presence_service import listing_is_unavailable
from app.services.price_tracking_service import _listing_status
from app.services.weekly_wishlist_digest_service import WeeklyWishlistDigestService


def test_listing_is_unavailable_covers_sold_and_inactive():
    assert listing_is_unavailable(SimpleNamespace(is_sold=True, status="ativo")) is True
    assert listing_is_unavailable(SimpleNamespace(is_sold=False, status="inativo")) is True
    assert listing_is_unavailable(SimpleNamespace(is_sold=False, status="ativo")) is False
    assert listing_is_unavailable(SimpleNamespace(is_sold=False, status="suspeito")) is False
    assert listing_is_unavailable(SimpleNamespace()) is False


def test_price_tracking_status_treats_inativo_as_inactive():
    assert _listing_status(SimpleNamespace(is_sold=False, status="inativo")) == "inactive"
    assert _listing_status(SimpleNamespace(is_sold=False, status="ativo")) == "active"
    assert _listing_status(None) == "orphan"


def test_weekly_digest_ignores_listing_marked_inativo(db):
    user = User(id=uuid.uuid4(), telegram_chat_id=777, username="u", is_active=True)
    db.add(user)
    db.commit()
    wl = Wishlist(user_id=user.id, query="civic", is_active=True)
    db.add(wl)
    db.commit()

    now = datetime.now(timezone.utc)
    for idx, status in enumerate(("ativo", "inativo")):
        listing = CarListing(
            source="olx",
            external_id=f"E{idx}",
            title=f"Carro {idx}",
            url=f"https://example/{idx}",
            price=10000,
            location="SP",
            status=status,
        )
        db.add(listing)
        db.commit()
        db.add(
            WishlistListingActivity(
                wishlist_id=wl.id,
                car_listing_id=listing.id,
                listing_identity_key=f"olx:E{idx}:{wl.id}",
                source_name="olx",
                source_listing_id=f"E{idx}",
                listing_url=listing.url,
                status="active",
                first_seen_at=now - timedelta(days=1),
                last_seen_at=now,
                missing_runs_count=0,
            )
        )
        db.commit()

    digest = WeeklyWishlistDigestService(db).build_all_digests()[0]
    assert digest.wishlists[0].total_active == 1
