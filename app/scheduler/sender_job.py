import logging
import time

from app.bot.sender import telegram_sender
from app.core.shutdown import is_shutdown_requested
from app.db.session import session_scope
from app.scheduler.jobs_send import send_queued_notifications
from app.services.system_logs_service import log, should_log_throttled

logger = logging.getLogger(__name__)


def job_send_notifications():
    if is_shutdown_requested():
        return
    t0 = time.time()
    with session_scope() as db:
        try:
            # ideal: send_queued_notifications retornar contagem
            n = send_queued_notifications(db, "sender", telegram_sender) or 0
            dt_ms = int((time.time() - t0) * 1000)
            # ocioso (nada enviado): 1 registro a cada 10 min; com envio, sempre
            if n or should_log_throttled("sender:job_ok_idle", 600):
                log(db, "info", "sender", "job ok", {"sent": n, "ms": dt_ms})
            db.commit()
        except Exception as e:
            db.rollback()
            dt_ms = int((time.time() - t0) * 1000)
            try:
                log(db, "error", "sender", "job failed", {"error": str(e), "ms": dt_ms})
            except Exception:
                db.rollback()
                logger.exception("sender job failed and failed to persist system log")
