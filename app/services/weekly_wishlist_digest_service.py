from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Iterable
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.car_listing import CarListing
from app.models.user import User
from app.models.wishlist import Wishlist
from app.models.wishlist_listing_activity import WishlistListingActivity


@dataclass(frozen=True)
class WeeklyDigestListing:
    listing_id: UUID
    title: str | None
    url: str
    price: Decimal | None
    location: str | None
    source: str
    created_at: datetime
    last_seen_at: datetime


@dataclass(frozen=True)
class WeeklyDigestWishlist:
    wishlist_id: UUID
    query: str
    total_active: int
    latest_listings: list[WeeklyDigestListing]


@dataclass(frozen=True)
class WeeklyDigestUser:
    user_id: UUID
    telegram_chat_id: int
    wishlists: list[WeeklyDigestWishlist]


class WeeklyWishlistDigestService:
    """Build weekly digest payloads based on current active listing activity."""

    def __init__(self, db: Session):
        self.db = db

    def list_eligible_users(self) -> list[User]:
        return (
            self.db.query(User)
            .filter(User.is_active.is_(True))
            .filter(User.telegram_chat_id.isnot(None))
            .filter(User.wishlists.any(Wishlist.is_active.is_(True)))
            .order_by(User.created_at.asc())
            .all()
        )

    def _active_rows_for_wishlist(self, wishlist_id: UUID) -> Iterable[tuple[WishlistListingActivity, CarListing]]:
        return (
            self.db.query(WishlistListingActivity, CarListing)
            .join(CarListing, CarListing.id == WishlistListingActivity.car_listing_id)
            .filter(WishlistListingActivity.wishlist_id == wishlist_id)
            .filter(WishlistListingActivity.status == "active")
            .filter(WishlistListingActivity.car_listing_id.isnot(None))
            .filter(CarListing.is_sold.is_(False))
            .order_by(WishlistListingActivity.last_seen_at.desc(), WishlistListingActivity.created_at.desc())
            .all()
        )

    def _build_wishlist_digest(self, wishlist: Wishlist) -> WeeklyDigestWishlist:
        rows = self._active_rows_for_wishlist(wishlist.id)

        # Defensive dedupe: if activity has multiple rows pointing to same listing id,
        # keep only the freshest row for digest.
        deduped: list[WeeklyDigestListing] = []
        seen_listing_ids: set[UUID] = set()
        for activity, listing in rows:
            if listing.id in seen_listing_ids:
                continue
            seen_listing_ids.add(listing.id)
            deduped.append(
                WeeklyDigestListing(
                    listing_id=listing.id,
                    title=listing.title,
                    url=listing.url,
                    price=listing.price,
                    location=listing.location,
                    source=listing.source,
                    created_at=listing.created_at,
                    last_seen_at=activity.last_seen_at,
                )
            )

        latest = deduped[:3]

        return WeeklyDigestWishlist(
            wishlist_id=wishlist.id,
            query=wishlist.query,
            total_active=len(deduped),
            latest_listings=latest,
        )

    def build_user_digest(self, user: User) -> WeeklyDigestUser | None:
        wishlists = (
            self.db.query(Wishlist)
            .filter(Wishlist.user_id == user.id)
            .filter(Wishlist.is_active.is_(True))
            .order_by(Wishlist.created_at.asc())
            .all()
        )
        if not wishlists:
            return None

        digest_wishlists = [self._build_wishlist_digest(w) for w in wishlists]
        return WeeklyDigestUser(
            user_id=user.id,
            telegram_chat_id=int(user.telegram_chat_id),
            wishlists=digest_wishlists,
        )

    def build_all_digests(self) -> list[WeeklyDigestUser]:
        out: list[WeeklyDigestUser] = []
        for user in self.list_eligible_users():
            item = self.build_user_digest(user)
            if item is None:
                continue
            out.append(item)
        return out
