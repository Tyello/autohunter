from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models.car_listing import CarListing
from app.models.wishlist_tracked_listing import WishlistTrackedListing


@dataclass
class PriceTrackingResult:
    tracked_id: str | None
    listing_id: str | None
    status: str
    direction: str | None
    price_changed: bool
    should_alert_price_drop: bool


def _now(now: datetime | None) -> datetime:
    return now or datetime.now(timezone.utc)


def _listing_status(listing: CarListing | None) -> str:
    if listing is None:
        return "orphan"
    if getattr(listing, "is_sold", False):
        return "inactive"
    return "active"


def sync_tracked_listing_price(
    db: Session,
    tracked: WishlistTrackedListing,
    listing: CarListing | None,
    now: datetime | None = None,
) -> PriceTrackingResult:
    _ = db
    current_now = _now(now)
    if listing is None:
        tracked.listing_status = "orphan"
        tracked.last_seen_at = current_now
        return PriceTrackingResult(str(tracked.id) if tracked.id else None, None, "orphan", None, False, False)

    current_price = listing.price
    previous_price = tracked.last_observed_price

    tracked.listing_status = _listing_status(listing)
    tracked.last_seen_at = listing.updated_at or current_now

    if tracked.initial_price is None and current_price is not None:
        tracked.initial_price = current_price

    if current_price is None:
        return PriceTrackingResult(str(tracked.id) if tracked.id else None, str(listing.id), tracked.listing_status or "active", None, False, False)

    if previous_price is None:
        tracked.last_observed_price = current_price
        return PriceTrackingResult(str(tracked.id) if tracked.id else None, str(listing.id), tracked.listing_status or "active", None, False, False)

    if current_price == previous_price:
        return PriceTrackingResult(str(tracked.id) if tracked.id else None, str(listing.id), tracked.listing_status or "active", "unchanged", False, False)

    delta = current_price - previous_price
    direction = "dropped" if delta < 0 else "increased"
    tracked.last_price_change_amount = delta
    if previous_price != 0:
        tracked.last_price_change_pct = delta / previous_price
    tracked.last_price_change_direction = direction
    tracked.last_price_change_at = current_now
    tracked.last_observed_price = current_price

    should_alert = delta < 0 and tracked.price_drop_alert_enabled and (
        tracked.last_price_drop_alert_price is None or current_price < tracked.last_price_drop_alert_price
    )

    return PriceTrackingResult(str(tracked.id) if tracked.id else None, str(listing.id), tracked.listing_status or "active", direction, True, should_alert)


def sync_price_tracking_for_listings(db: Session, listings: list[CarListing], now: datetime | None = None) -> list[PriceTrackingResult]:
    if not listings:
        return []
    listing_map = {row.id: row for row in listings if getattr(row, "id", None)}
    if not listing_map:
        return []

    tracked_rows = (
        db.query(WishlistTrackedListing)
        .filter(WishlistTrackedListing.car_listing_id.in_(list(listing_map.keys())))
        .all()
    )

    out: list[PriceTrackingResult] = []
    for tracked in tracked_rows:
        listing = listing_map.get(tracked.car_listing_id)
        out.append(sync_tracked_listing_price(db, tracked, listing, now=now))
    return out
