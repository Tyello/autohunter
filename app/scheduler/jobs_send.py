from datetime import datetime, timezone
from sqlalchemy.orm import Session

from app.core.settings import settings

from app.models.notification import Notification
from app.services.limits_service import can_send_more_today, should_send_daily_limit_notice
from app.services.system_logs_service import log

from app.bot.sender import send_daily_limit_notice_http


def send_queued_notifications(db: Session, component: str, sender_fn):
    queued = (
        db.query(Notification)
        .filter(Notification.status == "queued")
        .order_by(Notification.created_at.asc())
        .limit(10)
        .all()
    )

    sent = 0
    blocked = 0
    failed = 0

    for n in queued:
        # Limite diário: não acumula
        if not can_send_more_today(db, n.user_id):
            # 1) não é "failed": é política
            n.status = "suppressed"  # ou "limit_reached"
            n.error_message = "daily_limit_reached"
            db.commit()

            # 2) aviso 1x/dia
            user = n.user  # você já tem relationship no model Notification :contentReference[oaicite:4]{index=4}
            if user and should_send_daily_limit_notice(user):
                ok = send_daily_limit_notice_http(user, settings.default_alert_limit)
                if ok:
                    user.last_daily_limit_notice_at = datetime.now(timezone.utc)
                    db.commit()

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
