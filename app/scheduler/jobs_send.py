from datetime import datetime, timezone
from sqlalchemy.orm import Session

from app.models.notification import Notification
from app.services.limits_service import (
    can_send_more_today,
    get_active_subscription_limit_for_user,
    should_send_daily_limit_notice,
)
from app.services.notifications_service import mark_suppressed_reason
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
        if not can_send_more_today(db, n.user_id):
            # política (não é erro)
            mark_suppressed_reason(db, n.id, "daily_limit_reached")

            # aviso 1x por dia (no fuso do usuário)
            user = n.user
            if user and should_send_daily_limit_notice(user):
                limit = get_active_subscription_limit_for_user(db, n.user_id)
                ok = send_daily_limit_notice_http(user, limit)
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
            n.reason = None
            n.error_message = None
            db.commit()
            sent += 1
        except Exception as e:
            n.status = "failed"
            n.reason = "send_error"
            n.error_message = str(e)[:5000]
            db.commit()
            failed += 1

    log(db, "info", component, "send queued notifications result", {
        "sent": sent,
        "blocked_daily_limit": blocked,
        "failed": failed,
        "checked": len(queued),
    })

    # persiste o SystemLog (o sender já faz commits por notificação)
    db.commit()

    return sent
