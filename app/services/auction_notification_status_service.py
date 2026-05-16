from __future__ import annotations

from datetime import timezone

from app.core.settings import settings
from app.models.system_log import SystemLog
from app.services.auction_source_config_service import list_user_eligible_auction_sources

_STATUS_EVENTS = {
    "auction_notification_scheduler_tick_finished",
    "auction_notification_scheduler_tick_skipped",
    "auction_notification_scheduler_tick_failed",
    "auction_notification_job_skipped",
}


def _base_status(db) -> dict:
    return {
        "enabled": bool(getattr(settings, "auction_notifications_enabled", False)),
        "dry_run": bool(getattr(settings, "auction_notifications_dry_run", True)),
        "scheduler_minutes": int(getattr(settings, "auction_notifications_scheduler_minutes", 60) or 60),
        "max_wishlists": int(getattr(settings, "auction_notifications_max_wishlists_per_run", 20) or 20),
        "max_per_wishlist": int(getattr(settings, "auction_notifications_max_per_wishlist", 1) or 1),
        "max_per_user_per_day": int(getattr(settings, "auction_notifications_max_per_user_per_day", 3) or 3),
        "eligible_sources": sorted(list_user_eligible_auction_sources(db)),
        "last_run_at": "-",
        "last_status": "unknown",
        "last_reason": "-",
        "last_sent": 0,
        "last_previews": 0,
        "last_skipped_no_match": 0,
        "last_skipped_duplicate": 0,
        "last_skipped_daily_limit": 0,
        "last_errors": 0,
    }


def build_auction_notification_status(db) -> dict:
    out = _base_status(db)
    row = (
        db.query(SystemLog)
        .filter(SystemLog.component == "scheduler", SystemLog.message.in_(_STATUS_EVENTS))
        .order_by(SystemLog.created_at.desc())
        .first()
    )
    if not row:
        return out

    payload = row.payload or {}
    out["last_run_at"] = row.created_at.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC") if row.created_at else "-"
    out["last_reason"] = str(payload.get("reason") or "-")
    out["last_sent"] = int(payload.get("sent", 0) or 0)
    out["last_previews"] = int(payload.get("previews", 0) or 0)
    out["last_skipped_no_match"] = int(payload.get("skipped_no_match", 0) or 0)
    out["last_skipped_duplicate"] = int(payload.get("skipped_duplicate", 0) or 0)
    out["last_skipped_daily_limit"] = int(payload.get("skipped_daily_limit", 0) or 0)
    out["last_errors"] = int(payload.get("errors", 0) or 0)

    if row.message == "auction_notification_scheduler_tick_failed":
        out["last_status"] = "error"
    elif bool(payload.get("skipped")):
        out["last_status"] = "disabled" if payload.get("reason") == "disabled" else "skipped"
    elif out["last_sent"] > 0:
        out["last_status"] = "sent"
    elif bool(payload.get("dry_run")):
        out["last_status"] = "dry_run"
    else:
        out["last_status"] = "sent"
    return out
