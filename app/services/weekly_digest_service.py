from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.car_listing import CarListing
from app.models.notification import Notification
from app.models.wishlist import Wishlist


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _clamp_days(days: int) -> int:
    return max(1, min(30, int(days or 7)))


def build_weekly_digest_for_user(db: Session, *, user_id, days: int = 7, limit: int = 10) -> dict[str, Any]:
    days = _clamp_days(days)
    limit = max(1, min(20, int(limit or 10)))
    since = _utc_now() - timedelta(days=days)

    rows = (
        db.query(Notification, CarListing, Wishlist)
        .join(CarListing, CarListing.id == Notification.car_listing_id)
        .outerjoin(Wishlist, Wishlist.id == Notification.wishlist_id)
        .filter(Notification.user_id == user_id)
        .filter(Notification.status == "sent")
        .filter(Notification.sent_at.isnot(None))
        .filter(Notification.sent_at >= since)
        .order_by(Notification.sent_at.desc())
        .limit(500)
        .all()
    )

    total_sent = len(rows)
    by_wishlist: Counter[str] = Counter()
    by_reason: Counter[str] = Counter()
    by_status: Counter[str] = Counter()

    best_by_listing: dict[Any, dict[str, Any]] = {}
    price_drops: list[dict[str, Any]] = []

    for notif, listing, wishlist in rows:
        wishlist_name = (wishlist.query if wishlist and wishlist.query else "Sem wishlist").strip()
        by_wishlist[wishlist_name] += 1
        by_reason[(notif.reason or "unknown").strip()] += 1
        by_status[(notif.status or "unknown").strip()] += 1

        score = notif.score_v2 if notif.score_v2 is not None else -1
        existing = best_by_listing.get(listing.id)
        candidate = {
            "listing_id": str(listing.id),
            "title": listing.title or "Sem título",
            "url": listing.url,
            "price": float(listing.price) if listing.price is not None else None,
            "source": listing.source,
            "wishlist": wishlist_name,
            "score_v2": notif.score_v2,
            "sent_at": notif.sent_at,
        }
        if existing is None:
            best_by_listing[listing.id] = candidate
        else:
            existing_score = existing.get("score_v2") if existing.get("score_v2") is not None else -1
            if score > existing_score or (score == existing_score and notif.sent_at and existing.get("sent_at") and notif.sent_at > existing["sent_at"]):
                best_by_listing[listing.id] = candidate

        if (notif.reason or "").strip().lower() == "tracked_price_drop":
            price_drops.append(candidate)

    top_opportunities = sorted(
        best_by_listing.values(),
        key=lambda x: ((x.get("score_v2") if x.get("score_v2") is not None else -1), x.get("sent_at") or datetime.min.replace(tzinfo=timezone.utc)),
        reverse=True,
    )[:limit]

    dedup_drop = {}
    for item in sorted(price_drops, key=lambda x: x.get("sent_at") or datetime.min.replace(tzinfo=timezone.utc), reverse=True):
        dedup_drop[item["listing_id"]] = item
    drop_items = list(dedup_drop.values())[:limit]

    return {
        "user_id": str(user_id),
        "days": days,
        "window_start": since.isoformat(),
        "window_end": _utc_now().isoformat(),
        "totals": {
            "sent": total_sent,
            "wishlists_with_results": len(by_wishlist),
            "price_drops": len(drop_items),
        },
        "by_wishlist": [{"wishlist": k, "count": v} for k, v in by_wishlist.most_common(limit)],
        "by_reason": [{"reason": k, "count": v} for k, v in by_reason.most_common(limit)],
        "by_status": [{"status": k, "count": v} for k, v in by_status.most_common(limit)],
        "top_opportunities": top_opportunities,
        "price_drops": drop_items,
    }
