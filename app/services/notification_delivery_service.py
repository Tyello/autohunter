from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Iterable

from sqlalchemy.orm import Session

from app.core.settings import settings
from app.models.notification import Notification


RETRYABLE_KEYWORDS = (
    "timeout",
    "timed out",
    "temporarily",
    "too many requests",
    "retry",
    "connection reset",
    "service unavailable",
    "bad gateway",
)

TERMINAL_KEYWORDS = (
    "forbidden",
    "blocked",
    "bot was blocked",
    "chat not found",
    "user is deactivated",
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def reclaim_stale_processing_notifications(db: Session, *, now: datetime | None = None) -> int:
    now = now or _utcnow()
    ttl = int(getattr(settings, "notification_processing_ttl_seconds", 300) or 300)
    if ttl <= 0:
        return 0

    cutoff = now - timedelta(seconds=ttl)
    rows = (
        db.query(Notification)
        .filter(Notification.status == "processing")
        .filter(Notification.processing_started_at.isnot(None))
        .filter(Notification.processing_started_at < cutoff)
        .all()
    )
    for row in rows:
        row.status = "queued"
        row.processing_started_at = None
        row.processing_owner = None
        row.next_attempt_at = now
        row.reason = "processing_stale_requeued"
    return len(rows)


def claim_queued_notifications(
    db: Session,
    *,
    owner: str,
    batch_size: int | None = None,
    now: datetime | None = None,
) -> list[Notification]:
    now = now or _utcnow()
    batch = int(batch_size or getattr(settings, "notification_sender_batch_size", 20) or 20)
    if batch <= 0:
        return []

    reclaim_stale_processing_notifications(db, now=now)

    q = (
        db.query(Notification)
        .filter(Notification.status == "queued")
        .filter((Notification.next_attempt_at.is_(None)) | (Notification.next_attempt_at <= now))
        .order_by(Notification.created_at.asc())
    )
    try:
        q = q.with_for_update(skip_locked=True)
    except Exception:
        pass

    rows = q.limit(batch).all()
    for row in rows:
        row.status = "processing"
        row.processing_started_at = now
        row.processing_owner = owner[:120]

    return rows


def mark_notification_sent(row: Notification, *, now: datetime | None = None) -> None:
    now = now or _utcnow()
    row.status = "sent"
    row.sent_at = now
    row.reason = None
    row.error_message = None
    row.processing_started_at = None
    row.processing_owner = None


def classify_delivery_error(error_message: str) -> str:
    msg = (error_message or "").lower()
    if any(k in msg for k in TERMINAL_KEYWORDS):
        return "terminal"
    if any(k in msg for k in RETRYABLE_KEYWORDS):
        return "transient"
    return "unknown"


def mark_notification_delivery_error(
    row: Notification,
    *,
    error_message: str,
    now: datetime | None = None,
    retry_delay_seconds: int | None = None,
) -> str:
    now = now or _utcnow()
    row.attempts = int(row.attempts or 0) + 1

    err_kind = classify_delivery_error(error_message)
    row.error_message = (error_message or "")[:5000]
    row.processing_started_at = None
    row.processing_owner = None

    max_attempts = int(row.max_attempts or getattr(settings, "notification_max_attempts", 3) or 3)
    row.max_attempts = max_attempts

    if err_kind == "terminal":
        row.status = "failed"
        row.reason = "user_unreachable"
        row.next_attempt_at = None
        return "failed_terminal"

    if row.attempts >= max_attempts:
        row.status = "discarded"
        row.reason = "retry_exhausted"
        row.next_attempt_at = None
        return "discarded"

    base_delay = int(retry_delay_seconds or getattr(settings, "notification_retry_base_seconds", 30) or 30)
    delay = max(5, base_delay * row.attempts)
    row.status = "queued"
    row.reason = "retry_scheduled"
    row.next_attempt_at = now + timedelta(seconds=delay)
    return "retry_scheduled"


def mark_notification_failed_no_destination(row: Notification) -> None:
    row.status = "failed"
    row.reason = "missing_chat_id"
    row.error_message = "User telegram_chat_id is missing"
    row.processing_started_at = None
    row.processing_owner = None
    row.next_attempt_at = None


def summarize_statuses(rows: Iterable[Notification]) -> dict[str, int]:
    out = {"queued": 0, "processing": 0, "sent": 0, "failed": 0, "suppressed": 0, "discarded": 0}
    for row in rows:
        if row.status in out:
            out[row.status] += 1
    return out
