from datetime import datetime, timezone
from sqlalchemy.orm import Session

from app.models.notification import Notification


def create_queued(db: Session, user_id, wishlist_id, car_listing_id) -> Notification:
    row = Notification(
        user_id=user_id,
        wishlist_id=wishlist_id,
        car_listing_id=car_listing_id,
        status="queued",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def mark_sent(db: Session, notification_id):
    row = db.query(Notification).filter(Notification.id == notification_id).one()
    row.status = "sent"
    row.sent_at = datetime.now(timezone.utc)
    row.error_message = None
    db.commit()


def mark_failed(db: Session, notification_id, error_message: str):
    row = db.query(Notification).filter(Notification.id == notification_id).one()
    row.status = "failed"
    row.error_message = error_message[:5000]
    db.commit()


def mark_failed_reason(db: Session, notification_id, reason: str):
    row = db.query(Notification).filter(Notification.id == notification_id).one()
    row.status = "failed"
    row.error_message = reason[:5000]
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
    )
    db.add(row)
    db.commit()
    return True