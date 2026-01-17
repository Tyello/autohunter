import time

from app.db.session import SessionLocal
from app.services.system_logs_service import log
from app.services.notifications_cleanup_service import cleanup_old_notifications


def job_cleanup_notifications():
    t0 = time.time()
    with SessionLocal() as db:
        try:
            res = cleanup_old_notifications(db)
            dt_ms = int((time.time() - t0) * 1000)
            log(db, "info", "cleanup", "notifications cleanup ok", {**res, "ms": dt_ms})
        except Exception as e:
            dt_ms = int((time.time() - t0) * 1000)
            log(db, "error", "cleanup", "notifications cleanup failed", {"error": str(e), "ms": dt_ms})
