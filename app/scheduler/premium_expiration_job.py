from __future__ import annotations

import logging

from app.db.session import SessionLocal
from app.bot.sender import send_plain_text_to_user
from app.services.premium_subscription_service import expire_due_premium_subscriptions
from app.services.system_logs_service import log
from app.core.shutdown import is_shutdown_requested

logger = logging.getLogger(__name__)

def job_expire_premium_subscriptions():
    if is_shutdown_requested():
        return
    db = SessionLocal()
    try:
        result = expire_due_premium_subscriptions(db)
        for chat_id in result.expired_chat_ids:
            try:
                send_plain_text_to_user(chat_id, "Seu Premium expirou. Você voltou para o plano Free. Para renovar, use /upgrade.")
            except Exception:
                logger.warning("premium_expiration_notify_failed", extra={"chat_id": chat_id}, exc_info=True)
        log(
            db,
            "info",
            "premium_expiration_job",
            "premium_expiration_processed",
            {"expired_count": result.expired_count},
        )
        db.commit()
    finally:
        db.close()
