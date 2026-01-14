from datetime import datetime, timezone
from sqlalchemy.orm import Session

from app.models.notification import Notification
from app.services.limits_service import can_send_more_today
from app.services.system_logs_service import log
from app.services.notifications_service import mark_failed_reason


def send_queued_notifications(db: Session, component: str, sender_fn):
    queued = (
        db.query(Notification)
        .filter(Notification.status == "queued")
        .order_by(Notification.created_at.asc())
        .limit(50)
        .all()
    )

    sent = 0
    blocked = 0
    failed = 0

    for n in queued:
        # Limite diário: não acumula
        if not can_send_more_today(db, n.user_id):
            mark_failed_reason(db, n.id, "daily_limit_reached")
            blocked += 1
            continue

        user = n.user
        listing = n.car_listing

        try:
            sender_fn(n, listing, user)
            n.status = "sent"
            n.sent_at = datetime.now(timezone.utc)
            n.error_message = None
            db.commit()
            sent += 1
        except Exception as e:
            n.status = "failed"
            n.error_message = str(e)[:5000]
            db.commit()
            failed += 1

    log(db, "info", component, "send queued notifications result", {
        "sent": sent,
        "blocked_daily_limit": blocked,
        "failed": failed,
        "checked": len(queued),
    })
