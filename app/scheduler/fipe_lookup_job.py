import time

from app.core.shutdown import is_shutdown_requested
from app.db.session import session_scope
from app.services.system_logs_service import log
from app.services.fipe_on_demand_lookup_service import process_pending_fipe_lookups


def job_process_fipe_lookups():
    if is_shutdown_requested():
        return
    t0 = time.time()
    with session_scope() as db:
        try:
            res = process_pending_fipe_lookups(db)
            dt_ms = int((time.time() - t0) * 1000)
            log(db, "info", "fipe_lookup", "fipe on-demand lookup batch ok", {**res, "ms": dt_ms})
            db.commit()
        except Exception as e:
            dt_ms = int((time.time() - t0) * 1000)
            log(db, "error", "fipe_lookup", "fipe on-demand lookup batch failed", {"error": str(e), "ms": dt_ms})
            db.commit()
