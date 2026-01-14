from datetime import datetime, timezone
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.models.notification import Notification


DAILY_ALERT_LIMIT = 10


def can_send_more_today(db: Session, user_id) -> bool:
    # Conta "sent" desde 00:00 UTC do dia atual (simples e consistente)
    now = datetime.now(timezone.utc)
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    count = (
        db.query(func.count(Notification.id))
        .filter(Notification.user_id == user_id)
        .filter(Notification.status == "sent")
        .filter(Notification.sent_at >= day_start)
        .scalar()
    )
    return (count or 0) < DAILY_ALERT_LIMIT
