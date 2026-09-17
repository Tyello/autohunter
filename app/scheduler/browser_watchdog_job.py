import time

from app.core.settings import settings
from app.core.shutdown import is_shutdown_requested
from app.db.session import SessionLocal
from app.services.system_logs_service import log


def job_browser_process_watchdog() -> None:
    """Periodic sweep for orphaned Chromium/Playwright processes.

    Defense-in-depth: the hard-timeout recovery path in browser_queue_job.py is
    supposed to kill a wedged worker's entire process tree, but that tracking can
    miss a process (see playwright_pool.sweep_orphan_playwright_processes). Left
    alone, those orphans accumulate RAM run after run until the host runs out of
    memory. This job is the safety net independent of that tracking.
    """
    if not bool(getattr(settings, "enable_playwright", False)):
        return
    if is_shutdown_requested():
        return

    t0 = time.time()
    with SessionLocal() as db:
        try:
            from app.services.playwright_pool import sweep_orphan_playwright_processes

            res = sweep_orphan_playwright_processes(
                min_age_seconds=int(getattr(settings, "browser_watchdog_min_age_seconds", 120) or 120)
            )
            dt_ms = int((time.time() - t0) * 1000)
            killed = int(res.get("killed_count", 0) or 0)
            level = "warn" if killed > 0 else "debug"
            log(db, level, "browser_watchdog", "orphan_process_sweep", {**res, "ms": dt_ms})
            db.commit()
        except Exception as e:
            dt_ms = int((time.time() - t0) * 1000)
            log(db, "error", "browser_watchdog", "sweep_failed", {"error": str(e), "ms": dt_ms})
            db.commit()


def job_browser_worker_heartbeat_watchdog() -> None:
    """Proactively reset the Playwright worker if it's wedged inside a job.

    The reactive path (browser_fetcher.py catching a timeout and calling
    backend.reset()) only fires after some caller's own fetch has already
    queued behind the wedge and failed. Polling the worker's heartbeat lets
    us reset before that happens, so fewer scrapes get reported as failed
    for a wedge they had nothing to do with.
    """
    if not bool(getattr(settings, "enable_playwright", False)):
        return
    if is_shutdown_requested():
        return

    t0 = time.time()
    with SessionLocal() as db:
        try:
            from app.services.playwright_pool import recover_if_wedged

            res = recover_if_wedged(
                threshold_seconds=float(getattr(settings, "browser_worker_wedge_threshold_seconds", 150) or 150)
            )
            dt_ms = int((time.time() - t0) * 1000)
            if res.get("action") == "reset":
                log(db, "warn", "browser_watchdog", "worker_wedge_reset", {**res, "ms": dt_ms})
            elif res.get("action") == "reset_failed":
                log(db, "error", "browser_watchdog", "worker_wedge_reset_failed", {**res, "ms": dt_ms})
            else:
                log(db, "debug", "browser_watchdog", "worker_heartbeat_ok", {**res, "ms": dt_ms})
            db.commit()
        except Exception as e:
            dt_ms = int((time.time() - t0) * 1000)
            log(db, "error", "browser_watchdog", "heartbeat_check_failed", {"error": str(e), "ms": dt_ms})
            db.commit()
