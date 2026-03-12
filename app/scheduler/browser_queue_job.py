from __future__ import annotations

from datetime import datetime, timezone

from app.core.settings import settings
from app.db.session import SessionLocal
from app.services.system_logs_service import log
from app.services.source_execution_service import run_source_for_all_wishlists
from app.services.scrape_jobs_service import dequeue_next_job, mark_done, mark_failed


def _utcnow():
    return datetime.now(timezone.utc)


def job_browser_queue_worker():
    """Worker serial para jobs Playwright.

    Roda rápido e pega 1 job por ciclo. A ordem é garantida por:
    ORDER BY run_at ASC, priority DESC, created_at ASC
    """
    if not bool(getattr(settings, "enable_playwright", False)):
        return

    with SessionLocal() as db:
        job = None
        try:
            job = dequeue_next_job(db, queue="browser", lock_owner="browser_worker")
            if not job:
                db.commit()
                return

            db.commit()  # confirma lock + status=running

            t0 = _utcnow()
            res = run_source_for_all_wishlists(
                db,
                job.source,
                kind="queue",
                force=False,
                ignore_backoff=False,
            )
            dur_ms = int((_utcnow() - t0).total_seconds() * 1000)

            # Sucesso/erro "lógico" vira done; exceção vira failed (com retry)
            status = (res or {}).get("status") or "unknown"
            ok = bool((res or {}).get("ok", False))

            if ok:
                mark_done(job, result_status=status, payload=res, duration_ms=dur_ms)
            else:
                # blocked/error entram como done (já tem backoff no SourceState)
                if status in ("blocked", "error"):
                    mark_done(job, result_status=status, payload=res, duration_ms=dur_ms)
                else:
                    mark_done(job, result_status=f"not_ok:{status}", payload=res, duration_ms=dur_ms)

            db.commit()
        except Exception as e:
            try:
                if job is not None:
                    mark_failed(job, error=f"{type(e).__name__}: {e}", retry_in_seconds=60)
                    db.commit()
            except Exception as mark_exc:
                log(db, "warn", "browser_queue_worker", "suppressed_exception", {"stage": "worker.mark_failed", "exc_type": type(mark_exc).__name__, "message": str(mark_exc)[:240], "impact": "job_status_may_stay_running", "fallback": "worker_continues"})
                db.commit()
            try:
                log(db, "error", "browser_queue_worker", "job_failed", {"err": f"{type(e).__name__}: {e}"})
                db.commit()
            except Exception as log_exc:
                try:
                    log(db, "warn", "browser_queue_worker", "suppressed_exception", {"stage": "worker.log_job_failed", "exc_type": type(log_exc).__name__, "message": str(log_exc)[:240], "impact": "error_log_drop", "fallback": "worker_continues"})
                    db.commit()
                except Exception:
                    pass
