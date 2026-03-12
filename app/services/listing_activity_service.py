from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable
from uuid import UUID

from sqlalchemy import not_
from sqlalchemy.orm import Session

from app.models.car_listing import CarListing
from app.models.wishlist_listing_activity import WishlistListingActivity


@dataclass(frozen=True)
class SeenListingIdentity:
    listing_identity_key: str
    source_name: str
    source_listing_id: str | None
    listing_url: str | None
    car_listing_id: UUID | None


def build_seen_identity(listing: CarListing) -> SeenListingIdentity | None:
    source_name = (getattr(listing, "source", "") or "").strip().lower()
    if not source_name:
        return None

    source_listing_id = (getattr(listing, "external_id", None) or "").strip() or None
    listing_url = (getattr(listing, "url", None) or "").strip() or None

    if source_listing_id:
        key = f"src:{source_name}|id:{source_listing_id}"
    elif listing_url:
        key = f"src:{source_name}|url:{listing_url}"
    else:
        return None

    return SeenListingIdentity(
        listing_identity_key=key,
        source_name=source_name,
        source_listing_id=source_listing_id,
        listing_url=listing_url,
        car_listing_id=getattr(listing, "id", None),
    )


@dataclass(frozen=True)
class ActivityApplyStats:
    seen_upserts: int = 0
    missing_incremented: int = 0
    marked_inactive: int = 0
    reactivated: int = 0


@dataclass(frozen=True)
class ActivityReconcileStats:
    seen_upserts: int = 0
    missing_incremented: int = 0
    marked_inactive: int = 0
    reactivated: int = 0

    def to_dict(self) -> dict[str, int]:
        return {
            "seen_upserts": int(self.seen_upserts),
            "missing_incremented": int(self.missing_incremented),
            "marked_inactive": int(self.marked_inactive),
            "reactivated": int(self.reactivated),
        }


def _now() -> datetime:
    return datetime.now(timezone.utc)


def apply_seen_listings_for_wishlist(
    db: Session,
    *,
    wishlist_id: UUID,
    seen: Iterable[SeenListingIdentity],
    now: datetime | None = None,
    valid_run_id: UUID | None = None,
) -> ActivityApplyStats:
    t = now or _now()
    db.flush()
    seen_list = [s for s in (seen or []) if isinstance(s, SeenListingIdentity)]
    if not seen_list:
        return ActivityApplyStats()

    seen_unique: dict[str, SeenListingIdentity] = {}
    for ident in seen_list:
        seen_unique[ident.listing_identity_key] = ident
    seen_list = list(seen_unique.values())

    keys = [s.listing_identity_key for s in seen_list]
    existing_rows = (
        db.query(WishlistListingActivity)
        .filter(WishlistListingActivity.wishlist_id == wishlist_id)
        .filter(WishlistListingActivity.listing_identity_key.in_(keys))
        .all()
    )
    existing_by_key = {r.listing_identity_key: r for r in existing_rows}

    upserts = 0
    reactivated = 0

    for ident in seen_list:
        row = existing_by_key.get(ident.listing_identity_key)
        if row is None:
            row = WishlistListingActivity(
                wishlist_id=wishlist_id,
                car_listing_id=ident.car_listing_id,
                last_valid_run_id=valid_run_id,
                listing_identity_key=ident.listing_identity_key,
                source_name=ident.source_name,
                source_listing_id=ident.source_listing_id,
                listing_url=ident.listing_url,
                status="active",
                first_seen_at=t,
                last_seen_at=t,
                missing_runs_count=0,
                inactive_at=None,
                inactive_reason=None,
                reactivated_at=None,
            )
            db.add(row)
            existing_by_key[ident.listing_identity_key] = row
            upserts += 1
            continue

        row.car_listing_id = ident.car_listing_id or row.car_listing_id
        row.last_valid_run_id = valid_run_id
        row.source_name = ident.source_name
        row.source_listing_id = ident.source_listing_id
        row.listing_url = ident.listing_url or row.listing_url
        row.last_seen_at = t
        row.missing_runs_count = 0
        if row.status != "active":
            row.status = "active"
            row.reactivated_at = t
            row.inactive_at = None
            row.inactive_reason = None
            reactivated += 1
        upserts += 1

    return ActivityApplyStats(seen_upserts=upserts, reactivated=reactivated)


def apply_missing_for_wishlist_source(
    db: Session,
    *,
    wishlist_id: UUID,
    source_name: str,
    seen_identity_keys: set[str],
    missing_threshold: int,
    now: datetime | None = None,
    valid_run_id: UUID | None = None,
) -> ActivityApplyStats:
    src = (source_name or "").strip().lower()
    if not src:
        return ActivityApplyStats()

    t = now or _now()
    db.flush()
    threshold = max(1, int(missing_threshold or 1))

    q = (
        db.query(WishlistListingActivity)
        .filter(WishlistListingActivity.wishlist_id == wishlist_id)
        .filter(WishlistListingActivity.source_name == src)
        .filter(WishlistListingActivity.status == "active")
    )
    if seen_identity_keys:
        q = q.filter(not_(WishlistListingActivity.listing_identity_key.in_(list(seen_identity_keys))))

    rows = q.all()
    if not rows:
        return ActivityApplyStats()

    missing_incremented = 0
    marked_inactive = 0

    for row in rows:
        row.last_valid_run_id = valid_run_id
        row.missing_runs_count = int(row.missing_runs_count or 0) + 1
        missing_incremented += 1
        if row.missing_runs_count >= threshold and row.status != "inactive":
            row.status = "inactive"
            row.inactive_at = t
            row.inactive_reason = "missing_runs_threshold"
            marked_inactive += 1

    return ActivityApplyStats(
        missing_incremented=missing_incremented,
        marked_inactive=marked_inactive,
    )


def reconcile_listing_activity_for_source_run(
    db: Session,
    *,
    source_name: str,
    wishlist_seen: dict[UUID, list[SeenListingIdentity]],
    target_wishlist_ids: Iterable[UUID],
    missing_threshold: int,
    valid_run_id: UUID | None = None,
    now: datetime | None = None,
) -> ActivityReconcileStats:
    t = now or _now()

    seen_by_wishlist: dict[UUID, list[SeenListingIdentity]] = {
        wid: [s for s in (items or []) if isinstance(s, SeenListingIdentity)]
        for wid, items in (wishlist_seen or {}).items()
    }

    total_seen_upserts = 0
    total_missing_incremented = 0
    total_marked_inactive = 0
    total_reactivated = 0

    for wishlist_id in target_wishlist_ids or []:
        seen_items = seen_by_wishlist.get(wishlist_id, [])
        seen_keys = {s.listing_identity_key for s in seen_items}

        seen_stats = apply_seen_listings_for_wishlist(
            db,
            wishlist_id=wishlist_id,
            seen=seen_items,
            now=t,
            valid_run_id=valid_run_id,
        )
        total_seen_upserts += int(seen_stats.seen_upserts)
        total_reactivated += int(seen_stats.reactivated)

        missing_stats = apply_missing_for_wishlist_source(
            db,
            wishlist_id=wishlist_id,
            source_name=source_name,
            seen_identity_keys=seen_keys,
            missing_threshold=missing_threshold,
            now=t,
            valid_run_id=valid_run_id,
        )
        total_missing_incremented += int(missing_stats.missing_incremented)
        total_marked_inactive += int(missing_stats.marked_inactive)

    return ActivityReconcileStats(
        seen_upserts=total_seen_upserts,
        missing_incremented=total_missing_incremented,
        marked_inactive=total_marked_inactive,
        reactivated=total_reactivated,
    )
