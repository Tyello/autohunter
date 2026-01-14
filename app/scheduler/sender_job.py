from app.db.session import SessionLocal
from app.services.system_logs_service import log
from app.scheduler.jobs_send import send_queued_notifications
from app.bot.sender import telegram_sender


def job_send_notifications():
    with SessionLocal() as db:
        try:
            send_queued_notifications(db, "sender", telegram_sender)
        except Exception as e:
            log(db, "error", "sender", "job failed", {"error": str(e)})
