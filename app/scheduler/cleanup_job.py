import time

from app.core.shutdown import is_shutdown_requested
from app.db.session import SessionLocal
from app.services.system_logs_service import log
from app.services.notifications_cleanup_service import cleanup_old_notifications


def job_cleanup_notifications():
    if is_shutdown_requested():
        return
    t0 = time.time()
    with SessionLocal() as db:
        try:
            res = cleanup_old_notifications(db)
            dt_ms = int((time.time() - t0) * 1000)
            log(db, "info", "cleanup", "notifications cleanup ok", {**res, "ms": dt_ms})
            db.commit()
        except Exception as e:
            dt_ms = int((time.time() - t0) * 1000)
            log(db, "error", "cleanup", "notifications cleanup failed", {"error": str(e), "ms": dt_ms})
            db.commit()
