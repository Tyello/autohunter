import time
from app.db.session import SessionLocal
from app.services.system_logs_service import log
from app.scheduler.jobs_send import send_queued_notifications
from app.bot.sender import telegram_sender

def job_send_notifications():
    t0 = time.time()
    with SessionLocal() as db:
        try:
            # ideal: send_queued_notifications retornar contagem
            n = send_queued_notifications(db, "sender", telegram_sender) or 0
            dt_ms = int((time.time() - t0) * 1000)
            log(db, "info", "sender", "job ok", {"sent": n, "ms": dt_ms})
        except Exception as e:
            dt_ms = int((time.time() - t0) * 1000)
            log(db, "error", "sender", "job failed", {"error": str(e), "ms": dt_ms})
