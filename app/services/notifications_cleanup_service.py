from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models.notification import Notification


def cleanup_old_notifications(
    db: Session,
    *,
    keep_suppressed_days: int = 7,
    keep_sent_days: int = 30,
    keep_failed_days: int = 90,
) -> dict:
    """Report notification retention candidates without hard-deleting core data.

    `notifications` is protected by the database guardrail because it is part of
    user-facing delivery history. Runtime cleanup must not set break-glass or
    issue physical DELETE; destructive retention is an explicit maintenance task.
    """
    now = datetime.now(timezone.utc)
    cut_suppressed = now - timedelta(days=keep_suppressed_days)
    cut_sent = now - timedelta(days=keep_sent_days)
    cut_failed = now - timedelta(days=keep_failed_days)

    suppressed_candidates = (
        db.query(Notification)
        .filter(Notification.status == "suppressed")
        .filter(Notification.created_at < cut_suppressed)
        .count()
    )
    sent_candidates = (
        db.query(Notification)
        .filter(Notification.status == "sent")
        .filter(Notification.sent_at.isnot(None))
        .filter(Notification.sent_at < cut_sent)
        .count()
    )
    failed_candidates = (
        db.query(Notification)
        .filter(Notification.status == "failed")
        .filter(Notification.created_at < cut_failed)
        .count()
    )

    return {
        "deleted_suppressed": 0,
        "deleted_sent": 0,
        "deleted_failed": 0,
        "suppressed_candidates": int(suppressed_candidates or 0),
        "sent_candidates": int(sent_candidates or 0),
        "failed_candidates": int(failed_candidates or 0),
        "mode": "report_only_core_data_guardrail",
    }
