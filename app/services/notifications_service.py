from datetime import datetime, timezone
from sqlalchemy.orm import Session

from app.models.notification import Notification


def mark_failed(db: Session, notification_id, error_message: str):
    row = db.query(Notification).filter(Notification.id == notification_id).one()
    row.status = "failed"
    row.reason = "send_error"
    row.error_message = error_message[:5000]
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

