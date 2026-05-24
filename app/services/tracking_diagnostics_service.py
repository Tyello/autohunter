from __future__ import annotations

from datetime import datetime, timedelta, timezone
from sqlalchemy import func, case, or_

from app.models.notification import Notification
from app.models.system_log import SystemLog
from app.models.wishlist_tracked_listing import WishlistTrackedListing


MAX_EXAMPLES = 5


def build_tracking_diagnostics(db, *, window_hours: int = 24) -> dict:
    hours = max(1, min(168, int(window_hours or 24)))
    now = datetime.now(timezone.utc)
    window_start = now - timedelta(hours=hours)

    tracked_row = db.query(
        func.count(WishlistTrackedListing.id),
        func.sum(case((WishlistTrackedListing.price_drop_alert_enabled.is_(True), 1), else_=0)),
        func.sum(case((WishlistTrackedListing.listing_status == "active", 1), else_=0)),
        func.sum(case((WishlistTrackedListing.listing_status == "inactive", 1), else_=0)),
        func.sum(case((WishlistTrackedListing.listing_status == "orphan", 1), else_=0)),
        func.sum(case((or_(WishlistTrackedListing.listing_status.is_(None), WishlistTrackedListing.listing_status == ""), 1), else_=0)),
        func.sum(case((WishlistTrackedListing.last_observed_price.is_(None), 1), else_=0)),
        func.sum(case((WishlistTrackedListing.last_seen_at.is_(None), 1), else_=0)),
        func.sum(case((WishlistTrackedListing.last_price_change_at.is_not(None), 1), else_=0)),
        func.sum(case((WishlistTrackedListing.last_price_change_direction == "dropped", 1), else_=0)),
        func.sum(case((WishlistTrackedListing.last_price_change_direction == "increased", 1), else_=0)),
        func.sum(case((or_(WishlistTrackedListing.last_price_change_direction.is_(None), WishlistTrackedListing.last_price_change_direction == "", WishlistTrackedListing.last_price_change_direction == "unchanged"), 1), else_=0)),
    ).one()

    notif_counts = dict(
        db.query(Notification.status, func.count(Notification.id))
        .filter(Notification.reason == "tracked_price_drop", Notification.created_at >= window_start)
        .group_by(Notification.status)
        .all()
    )

    latest_alert = (
        db.query(Notification.created_at)
        .filter(Notification.reason == "tracked_price_drop")
        .order_by(Notification.created_at.desc())
        .limit(1)
        .scalar()
    )

    latest_tracking_job = (
        db.query(SystemLog)
        .filter(
            SystemLog.created_at >= window_start,
            or_(SystemLog.component.ilike("%tracking%"), SystemLog.message.ilike("%tracking%"), SystemLog.message.ilike("%price_drop%")),
        )
        .order_by(SystemLog.created_at.desc())
        .limit(1)
        .one_or_none()
    )

    orphan_examples = (
        db.query(WishlistTrackedListing)
        .filter(WishlistTrackedListing.listing_status == "orphan")
        .order_by(WishlistTrackedListing.updated_at.desc())
        .limit(MAX_EXAMPLES)
        .all()
    )
    drop_examples = (
        db.query(WishlistTrackedListing)
        .filter(WishlistTrackedListing.last_price_change_direction == "dropped")
        .order_by(WishlistTrackedListing.last_price_change_at.desc())
        .limit(MAX_EXAMPLES)
        .all()
    )
    pending_alerts = (
        db.query(Notification)
        .filter(Notification.reason == "tracked_price_drop", Notification.status.in_(["queued", "processing"]))
        .order_by(Notification.created_at.desc())
        .limit(MAX_EXAMPLES)
        .all()
    )

    return {
        "window_hours": hours,
        "tracked": {
            "total": int(tracked_row[0] or 0),
            "price_drop_alert_enabled": int(tracked_row[1] or 0),
            "active": int(tracked_row[2] or 0),
            "inactive": int(tracked_row[3] or 0),
            "orphan": int(tracked_row[4] or 0),
            "unknown": int(tracked_row[5] or 0),
            "last_observed_price_null": int(tracked_row[6] or 0),
            "last_seen_at_null": int(tracked_row[7] or 0),
            "price_change_recorded": int(tracked_row[8] or 0),
            "dropped": int(tracked_row[9] or 0),
            "increased": int(tracked_row[10] or 0),
            "unchanged_or_null": int(tracked_row[11] or 0),
        },
        "price_drop_notifications": {
            "queued": int(notif_counts.get("queued", 0)),
            "processing": int(notif_counts.get("processing", 0)),
            "sent": int(notif_counts.get("sent", 0)),
            "failed": int((notif_counts.get("failed", 0) + notif_counts.get("error", 0))),
            "latest_created_at": latest_alert,
        },
        "last_tracking_job": {
            "created_at": latest_tracking_job.created_at if latest_tracking_job else None,
            "level": latest_tracking_job.level if latest_tracking_job else None,
            "component": latest_tracking_job.component if latest_tracking_job else None,
            "message": latest_tracking_job.message if latest_tracking_job else None,
        },
        "examples": {
            "orphans": [
                {"wishlist_id": str(x.wishlist_id), "slot": x.slot, "updated_at": x.updated_at} for x in orphan_examples
            ],
            "recent_drops": [
                {"wishlist_id": str(x.wishlist_id), "slot": x.slot, "price": x.last_observed_price, "at": x.last_price_change_at}
                for x in drop_examples
            ],
            "pending_alerts": [
                {"status": x.status, "created_at": x.created_at, "wishlist_id": str(x.wishlist_id) if x.wishlist_id else "-"}
                for x in pending_alerts
            ],
        },
    }
