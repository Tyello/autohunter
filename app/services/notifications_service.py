from datetime import datetime, timezone
from sqlalchemy.orm import Session

from app.models.notification import Notification


def create_queued(db: Session, user_id, wishlist_id, car_listing_id) -> Notification:
    row = Notification(
        user_id=user_id,
        wishlist_id=wishlist_id,
        car_listing_id=car_listing_id,
        status="queued",
        next_attempt_at=datetime.now(timezone.utc),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def mark_sent(db: Session, notification_id):
    row = db.query(Notification).filter(Notification.id == notification_id).one()
    row.status = "sent"
    row.sent_at = datetime.now(timezone.utc)
    row.reason = None
    row.error_message = None
    row.processing_started_at = None
    row.processing_owner = None
    db.commit()


def mark_failed(db: Session, notification_id, error_message: str):
    row = db.query(Notification).filter(Notification.id == notification_id).one()
    row.status = "failed"
    row.reason = "send_error"
    row.error_message = error_message[:5000]
    row.processing_started_at = None
    row.processing_owner = None
    db.commit()


def mark_failed_reason(db: Session, notification_id, reason: str, error_message: str | None = None):
    """Marca como failed com um motivo curto e, opcionalmente, uma mensagem detalhada."""
    row = db.query(Notification).filter(Notification.id == notification_id).one()
    row.status = "failed"
    row.reason = reason
    row.error_message = (error_message or reason)[:5000]
    row.processing_started_at = None
    row.processing_owner = None
    db.commit()


def mark_suppressed_reason(db: Session, notification_id, reason: str):
    """Marca como suppressed (politica/regra de negocio), sem contar como erro."""
    row = db.query(Notification).filter(Notification.id == notification_id).one()
    row.status = "suppressed"
    row.reason = reason
    row.error_message = None
    row.processing_started_at = None
    row.processing_owner = None
    db.commit()


def notification_exists(db: Session, user_id, wishlist_id, car_listing_id) -> bool:
    return (
        db.query(Notification.id)
        .filter(Notification.user_id == user_id)
        .filter(Notification.wishlist_id == wishlist_id)
        .filter(Notification.car_listing_id == car_listing_id)
        .first()
        is not None
    )


def create_queued_if_absent(db: Session, user_id, wishlist_id, car_listing_id) -> bool:
    if notification_exists(db, user_id, wishlist_id, car_listing_id):
        return False

    row = Notification(
        user_id=user_id,
        wishlist_id=wishlist_id,
        car_listing_id=car_listing_id,
        status="queued",
        next_attempt_at=datetime.now(timezone.utc),
    )
    db.add(row)
    db.commit()
    return True
