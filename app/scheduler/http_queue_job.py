from __future__ import annotations

from datetime import datetime, timezone

from app.core.settings import settings
from app.db.session import SessionLocal
from app.services.system_logs_service import log
from app.services.source_execution_service import run_source_for_all_wishlists
from app.services.scrape_jobs_service import dequeue_next_job, mark_done, mark_failed


def _utcnow():
    return datetime.now(timezone.utc)


def job_http_queue_worker(worker_id: str = "http_worker"):
    """Worker para jobs HTTP.

    Similar ao worker Playwright, mas roda em pool (ThreadPoolExecutor) e consome a fila 'http'.
    A fila é deduplicada por (source, queue) enquanto houver job ativo, evitando starvation
    (ex.: MercadoLivre rodando em loop e impedindo outras fontes).
    """
    with SessionLocal() as db:
        job = None
        try:
            job = dequeue_next_job(db, queue="http", lock_owner=worker_id)
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

            status = (res or {}).get("status") or "unknown"
            ok = bool((res or {}).get("ok", False))

            if ok:
                mark_done(job, result_status=status, payload=res, duration_ms=dur_ms)
            else:
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
                log(db, "warn", "http_queue_worker", "suppressed_exception", {"stage": "worker.mark_failed", "exc_type": type(mark_exc).__name__, "message": str(mark_exc)[:240], "impact": "job_status_may_stay_running", "fallback": "worker_continues"})
                db.commit()
            try:
                log(db, "error", worker_id, "job_failed", {"err": f"{type(e).__name__}: {e}"})
                db.commit()
            except Exception as log_exc:
                try:
                    log(db, "warn", "http_queue_worker", "suppressed_exception", {"stage": "worker.log_job_failed", "exc_type": type(log_exc).__name__, "message": str(log_exc)[:240], "impact": "error_log_drop", "fallback": "worker_continues"})
                    db.commit()
                except Exception:
                    pass
