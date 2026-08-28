from __future__ import annotations

import threading
from datetime import datetime, timezone

from app.core.settings import settings
from app.core.shutdown import is_shutdown_requested
from app.db.session import SessionLocal
from app.models.scrape_job import ScrapeJob
from app.services.system_logs_service import log
from app.services.source_execution_service import run_source_for_all_wishlists
from app.services.scrape_jobs_service import dequeue_next_job, mark_done, mark_failed


def _utcnow():
    return datetime.now(timezone.utc)


def _reset_playwright_pool_best_effort() -> None:
    """Discard a possibly-wedged Playwright worker thread and start a fresh one.

    Best-effort: never raises. Used when a job run exceeds its hard wall-clock
    budget, which usually means the dedicated Playwright worker thread is stuck
    inside a blocking browser call (frozen/zombie Chromium process) and would
    otherwise starve every future execution forever.
    """
    try:
        if getattr(settings, "playwright_endpoint", None):
            return  # external browser service: nothing local to reset
        from app.services.playwright_pool import get_playwright_pool
        get_playwright_pool().reset()
    except Exception:
        pass


def _handle_hard_timeout(job_id: int, source: str, dur_ms: int, hard_timeout_s: int) -> None:
    """Force-fail/requeue a job whose worker thread is still stuck, using a
    brand-new session so we never touch the (possibly still in-use) session
    owned by the wedged worker thread.
    """
    _reset_playwright_pool_best_effort()
    try:
        with SessionLocal() as db2:
            job2 = db2.get(ScrapeJob, job_id)
            if job2 is not None and job2.status == "running":
                mark_failed(job2, error=f"hard_timeout_after_{dur_ms}ms", retry_in_seconds=60)
            log(
                db2,
                "error",
                "browser_queue_worker",
                "job_hard_timeout",
                {"job_id": job_id, "source": source, "dur_ms": dur_ms, "hard_timeout_s": hard_timeout_s},
            )
            db2.commit()
    except Exception:
        pass


def _log_best_effort(db, level: str, component: str, message: str, payload: dict) -> None:
    """Write a system_logs row on its own commit boundary.

    A failure here (bad payload, transient DB error, whatever) must never
    propagate: logging is never allowed to be a single point of failure that
    blocks a job from being marked done/failed. If the insert or its commit
    fails, roll back just this log attempt and move on.
    """
    try:
        log(db, level, component, message, payload)
        db.commit()
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass


def job_browser_queue_worker():
    """Worker serial para jobs Playwright.

    Roda rápido e pega 1 job por ciclo. A ordem é garantida por:
    ORDER BY run_at ASC, priority DESC, created_at ASC

    A execução do scrape roda numa thread filha com um orçamento máximo de
    tempo (settings.browser_queue_job_hard_timeout_seconds). Se estourar, o
    worker NÃO fica bloqueado esperando: ele libera o slot do executor
    "browser" do APScheduler (evitando o travamento indefinido de
    max_instances=1) e força o job para failed/retry usando uma sessão nova.
    A thread filha pode continuar rodando em segundo plano (órfã) até
    terminar ou até o processo reiniciar; seu resultado é descartado.

    Lifecycle da sessão: `db` é criada e fechada dentro desta única execução
    (nunca reaproveitada entre chamadas). Se qualquer commit falhar no meio do
    caminho (inclusive commits internos feitos por run_source_for_all_wishlists
    dentro da thread filha), a sessão fica em estado "pending rollback" e
    PRECISA de um db.rollback() explícito antes de ser reutilizada — do
    contrário todo commit seguinte levanta PendingRollbackError, mascarando o
    erro original e impedindo até o mark_failed() de ser persistido (o job
    fica "running" pra sempre e trava o slot do APScheduler).
    """
    if not bool(getattr(settings, "enable_playwright", False)):
        return

    if is_shutdown_requested():
        return

    db = SessionLocal()
    job = None
    try:
        try:
            job = dequeue_next_job(db, queue="browser", lock_owner="browser_worker")
            db.commit()  # confirma lock + status=running (ou no-op se não há job)
        except Exception:
            db.rollback()
            raise

        if not job:
            return

        job_id = job.id
        job_source = job.source

        hard_timeout_s = max(30, int(getattr(settings, "browser_queue_job_hard_timeout_seconds", 240) or 240))

        result_box: dict = {}

        def _do_scrape():
            try:
                result_box["res"] = run_source_for_all_wishlists(
                    db,
                    job.source,
                    kind="queue",
                    force=False,
                    ignore_backoff=False,
                )
            except Exception as e:  # noqa: BLE001
                result_box["exc"] = e

        t0 = _utcnow()
        worker_thread = threading.Thread(
            target=_do_scrape, name=f"browser_queue_job:{job_source}", daemon=True
        )
        worker_thread.start()
        worker_thread.join(timeout=hard_timeout_s)
        dur_ms = int((_utcnow() - t0).total_seconds() * 1000)

        if worker_thread.is_alive():
            # The scrape is stuck past its budget. Do NOT touch `db` from this
            # point on: the child thread may still be using it concurrently.
            _handle_hard_timeout(job_id, job_source, dur_ms, hard_timeout_s)
            return

        if "exc" in result_box:
            # run_source_for_all_wishlists may have committed some steps and
            # failed mid-way through a later one: the session can already be
            # in "pending rollback" state. Clear it before touching `db` again.
            try:
                db.rollback()
            except Exception:
                pass
            raise result_box["exc"]

        res = result_box.get("res")

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

        # Job status is committed on its own boundary first, so a logging
        # failure below can never roll back or block the job's completion.
        try:
            db.commit()
        except Exception:
            db.rollback()
            raise
    except Exception as e:
        err_text = f"{type(e).__name__}: {e}"
        shutdown_exc = is_shutdown_requested() or "cannot schedule new futures after interpreter shutdown" in str(e).lower()

        try:
            db.rollback()
        except Exception:
            pass

        if job is not None and not shutdown_exc:
            try:
                mark_failed(job, error=err_text, retry_in_seconds=60)
                db.commit()
            except Exception as mark_exc:
                try:
                    db.rollback()
                except Exception:
                    pass
                _log_best_effort(
                    db,
                    "warn",
                    "browser_queue_worker",
                    "suppressed_exception",
                    {"stage": "worker.mark_failed", "exc_type": type(mark_exc).__name__, "message": str(mark_exc)[:240], "impact": "job_status_may_stay_running", "fallback": "worker_continues"},
                )

        if shutdown_exc:
            _log_best_effort(db, "info", "browser_queue_worker", "shutdown_suppressed", {"err": err_text})
        else:
            _log_best_effort(db, "error", "browser_queue_worker", "job_failed", {"err": err_text})
    finally:
        try:
            db.close()
        except Exception:
            pass
