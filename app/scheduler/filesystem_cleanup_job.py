import time

from app.core.shutdown import is_shutdown_requested
from app.db.session import SessionLocal
from app.services.filesystem_cleanup_service import run_filesystem_cleanup
from app.services.system_logs_service import log


def job_filesystem_cleanup_daily() -> None:
    if is_shutdown_requested():
        return
    t0 = time.time()
    with SessionLocal() as db:
        try:
            res = run_filesystem_cleanup()
            dt_ms = int((time.time() - t0) * 1000)
            level = "info" if int(res.get("deleted_total", 0) or 0) > 0 else "debug"
            log(db, level, "cleanup", "filesystem cleanup run", {**res, "ms": dt_ms})
            db.commit()
        except Exception as e:
            dt_ms = int((time.time() - t0) * 1000)
            log(db, "error", "cleanup", "filesystem cleanup failed", {"error": str(e), "ms": dt_ms})
            db.commit()
