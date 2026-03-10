from datetime import datetime, timezone
from sqlalchemy.orm import Session

from app.services.limits_service import (
    can_send_more_today,
    get_active_subscription_limit_for_user,
    should_send_daily_limit_notice,
)
from app.services.notification_delivery_service import (
    claim_queued_notifications,
    mark_notification_delivery_error,
    mark_notification_failed_no_destination,
    mark_notification_sent,
)
from app.services.notifications_service import mark_suppressed_reason
from app.services.system_logs_service import log

from app.bot.sender import send_daily_limit_notice_http


def send_queued_notifications(db: Session, component: str, sender_fn):
    queued = claim_queued_notifications(db, owner=component)

    sent = 0
    blocked = 0
    failed = 0
    retried = 0
    discarded = 0

    for n in queued:
        user = n.user
        if not user or not getattr(user, "telegram_chat_id", None):
            mark_notification_failed_no_destination(n)
            db.commit()
            failed += 1
            continue

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

        listing = n.car_listing
        try:
            sender_fn(n, listing, user)
            mark_notification_sent(n)
            db.commit()
            sent += 1
        except Exception as e:
            outcome = mark_notification_delivery_error(n, error_message=str(e))
            db.commit()
            if outcome == "retry_scheduled":
                retried += 1
            elif outcome == "discarded":
                discarded += 1
            else:
                failed += 1

    log(db, "info", component, "send queued notifications result", {
        "claimed": len(queued),
        "sent": sent,
        "blocked_daily_limit": blocked,
        "failed": failed,
        "retried": retried,
        "discarded": discarded,
    })

    # persiste o SystemLog (o sender já faz commits por notificação)
    db.commit()

    return sent
