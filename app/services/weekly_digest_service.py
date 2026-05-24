from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import case, func
from sqlalchemy.orm import Session

from app.models.car_listing import CarListing
from app.models.notification import Notification
from app.models.user import User
from app.models.wishlist import Wishlist
from app.models.user_digest_preference import UserDigestPreference


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
    by_source: Counter[str] = Counter()

    best_by_listing: dict[Any, dict[str, Any]] = {}
    price_drops: list[dict[str, Any]] = []

    for notif, listing, wishlist in rows:
        wishlist_name = (wishlist.query if wishlist and wishlist.query else "Sem wishlist").strip()
        by_wishlist[wishlist_name] += 1
        by_reason[(notif.reason or "unknown").strip()] += 1
        by_status[(notif.status or "unknown").strip()] += 1
        by_source[(listing.source or "unknown").strip()] += 1

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
            "year": listing.year,
            "mileage_km": listing.mileage_km,
            "city": listing.city,
            "state": listing.state,
            "location": listing.location,
            "score_breakdown": (notif.score_breakdown or {}) if isinstance(notif.score_breakdown, dict) else {},
            "reason": (notif.reason or "").strip() or None,
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
        if item["listing_id"] not in dedup_drop:
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
        "by_source": [{"source": k, "count": v} for k, v in by_source.most_common(limit)],
        "by_reason": [{"reason": k, "count": v} for k, v in by_reason.most_common(limit)],
        "by_status": [{"status": k, "count": v} for k, v in by_status.most_common(limit)],
        "top_opportunities": top_opportunities,
        "price_drops": drop_items,
        "recent_alerts": sorted(best_by_listing.values(), key=lambda x: x.get("sent_at") or datetime.min.replace(tzinfo=timezone.utc), reverse=True)[:limit],
    }


def build_weekly_digest_candidates(db: Session, *, days: int = 7, limit: int = 20, only_enabled: bool = False) -> list[dict[str, Any]]:
    days = _clamp_days(days)
    limit = max(1, min(50, int(limit or 20)))
    since = _utc_now() - timedelta(days=days)

    rows_query = (
        db.query(
            Notification.user_id.label("user_id"),
            User.telegram_chat_id.label("telegram_chat_id"),
            User.username.label("username"),
            func.count(Notification.id).label("total_sent"),
            func.count(func.distinct(Notification.wishlist_id)).label("total_wishlists_with_results"),
            func.sum(case((func.lower(func.coalesce(Notification.reason, "")) == "tracked_price_drop", 1), else_=0)).label(
                "total_price_drops"
            ),
            func.max(Notification.sent_at).label("latest_sent_at"),
            func.max(Notification.score_v2).label("top_score_v2"),
        )
        .join(User, User.id == Notification.user_id)
        .outerjoin(UserDigestPreference, UserDigestPreference.user_id == Notification.user_id)
        .filter(Notification.status == "sent")
        .filter(Notification.sent_at.isnot(None))
        .filter(Notification.sent_at >= since)
        .group_by(Notification.user_id, User.telegram_chat_id, User.username)
        .order_by(
            func.count(Notification.id).desc(),
            func.sum(case((func.lower(func.coalesce(Notification.reason, "")) == "tracked_price_drop", 1), else_=0)).desc(),
            func.max(Notification.sent_at).desc(),
        )
    )
    if only_enabled:
        rows_query = rows_query.filter(UserDigestPreference.weekly_digest_enabled.is_(True))
    rows = rows_query.limit(limit).all()

    if not rows:
        return []

    user_ids = [row.user_id for row in rows]
    sample_rows = (
        db.query(Notification.user_id, Wishlist.query, CarListing.title, Notification.sent_at)
        .join(CarListing, CarListing.id == Notification.car_listing_id)
        .outerjoin(Wishlist, Wishlist.id == Notification.wishlist_id)
        .filter(Notification.user_id.in_(user_ids))
        .filter(Notification.status == "sent")
        .filter(Notification.sent_at.isnot(None))
        .filter(Notification.sent_at >= since)
        .order_by(Notification.sent_at.desc())
        .limit(limit * 40)
        .all()
    )

    sample_wishlist_names: dict[Any, list[str]] = defaultdict(list)
    sample_listing_titles: dict[Any, list[str]] = defaultdict(list)
    for user_id, wishlist_query, listing_title, _sent_at in sample_rows:
        wishlist_name = (wishlist_query or "Sem wishlist").strip()
        title = (listing_title or "Sem título").strip()
        if wishlist_name and wishlist_name not in sample_wishlist_names[user_id] and len(sample_wishlist_names[user_id]) < 3:
            sample_wishlist_names[user_id].append(wishlist_name)
        if title and title not in sample_listing_titles[user_id] and len(sample_listing_titles[user_id]) < 3:
            sample_listing_titles[user_id].append(title)

    candidates = []
    for row in rows:
        candidates.append(
            {
                "user_id": str(row.user_id),
                "telegram_chat_id": row.telegram_chat_id,
                "username": row.username,
                "total_sent": int(row.total_sent or 0),
                "total_wishlists_with_results": int(row.total_wishlists_with_results or 0),
                "total_price_drops": int(row.total_price_drops or 0),
                "latest_sent_at": row.latest_sent_at,
                "top_score_v2": row.top_score_v2,
                "sample_wishlist_names": sample_wishlist_names.get(row.user_id, []),
                "sample_listing_titles": sample_listing_titles.get(row.user_id, []),
            }
        )
    return candidates
