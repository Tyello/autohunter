import time

from app.core.shutdown import is_shutdown_requested
from app.db.session import SessionLocal
from app.services.system_logs_service import log
from app.services.operational_data_cleanup_service import run_operational_cleanup


def job_operational_data_cleanup():
    if is_shutdown_requested():
        return
    t0 = time.time()
    with SessionLocal() as db:
        try:
            res = run_operational_cleanup(db)
            dt_ms = int((time.time() - t0) * 1000)
            log(db, "info", "cleanup", "operational data cleanup ok", {**res, "ms": dt_ms})
            db.commit()
        except Exception as e:
            dt_ms = int((time.time() - t0) * 1000)
            log(db, "error", "cleanup", "operational data cleanup failed", {"error": str(e), "ms": dt_ms})
            db.commit()
