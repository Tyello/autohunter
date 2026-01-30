from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.executors.pool import ThreadPoolExecutor

import threading

from app.core.settings import settings
from app.db.session import SessionLocal
from app.sources import list_sources
from app.scheduler.heartbeat import heartbeat

from app.services.system_logs_service import log
from app.services.source_backoff_service import mark_skipped
from app.services.source_runs_service import record_run
from app.services.source_execution_service import run_source_for_all_wishlists as _exec_source_for_all_wishlists


# Hard cap parallel scraping jobs (protects Raspberry Pi CPU/RAM and reduces ban risk)
_MAX_PAR = int(getattr(settings, "scheduler_max_parallel_sources", 1) or 1)
_SOURCE_JOBS_SEM = threading.BoundedSemaphore(_MAX_PAR if _MAX_PAR > 0 else 1)


def job_run_source_for_all_wishlists(source_name: str):
    """Scheduler tick for one source (DB-driven).

    Cadence and operational config come from DB:
    - source_configs: enable/schedule/cooldown/rate-limit/proxy/browser flags
    - source_states: backoff and last_effective_run_at (due checks)
    """
    # Non-blocking: if another source is running, skip this tick.
    if not _SOURCE_JOBS_SEM.acquire(blocking=False):
        with SessionLocal() as db:
            src = (source_name or "").lower().strip()
            mark_skipped(db, src, "parallel_limit")
            record_run(db, source=src, kind="scheduler", status="skipped", payload={"reason": "parallel_limit"})
            db.commit()
        return

    try:
        with SessionLocal() as db:
            try:
                _exec_source_for_all_wishlists(db, source_name, kind="scheduler", force=False, ignore_backoff=False)
                db.commit()
            except Exception as e:
                # last-resort guard: don't let the scheduler thread die
                try:
                    log(db, "error", f"scheduler_{source_name}", "tick_failed", {"err": str(e)[:300]})
                    db.commit()
                except Exception:
                    pass
    finally:
        try:
            _SOURCE_JOBS_SEM.release()
        except Exception:
            pass


def start_scheduler() -> BackgroundScheduler:
    sched = BackgroundScheduler(
        timezone="UTC",
        executors={"default": ThreadPoolExecutor(int(getattr(settings, "scheduler_workers", 4) or 4))},
        job_defaults={
            "coalesce": True,
            "misfire_grace_time": 60,
            "max_instances": 1,
        },
    )

    # Smoke test Playwright no boot (falha cedo em caso de bug/config/permissões)
    if bool(getattr(settings, "playwright_smoke_on_boot", True)):
        try:
            from app.services.playwright_smoke import assert_playwright_ready
            from app.services.admin_programming_alerts import maybe_alert_programming_error

            with SessionLocal() as db:
                try:
                    assert_playwright_ready()
                except Exception as e:
                    log(db, "error", "boot", "playwright_smoke_failed", {"err": f"{type(e).__name__}: {e}"})
                    db.commit()
                    try:
                        maybe_alert_programming_error("boot/playwright", e)
                    except Exception:
                        pass
        except Exception:
            # nunca deixa o scheduler morrer por causa do smoke
            pass

    # Pluggable sources: schedule a small "tick" for each source.
    # Real cadence is DB-driven (source_configs.sched_minutes + source_states.last_effective_run_at).
    tick_seconds = int(getattr(settings, "scheduler_tick_seconds", 60) or 60)
    tick_seconds = max(15, min(tick_seconds, 300))  # clamp: 15s..5m

    for plugin in list_sources():
        if not plugin.supports_wishlist_monitoring:
            continue
        job_id = f"{plugin.name}_tick"
        sched.add_job(
            lambda n=plugin.name: job_run_source_for_all_wishlists(n),
            "interval",
            seconds=tick_seconds,
            id=job_id,
            replace_existing=True,
        )

    def _job_heartbeat():
        db = SessionLocal()
        try:
            heartbeat(db)
            db.commit()
        finally:
            db.close()

    sched.add_job(_job_heartbeat, "interval", seconds=10, id="heartbeat", replace_existing=True)

    from app.scheduler.sender_job import job_send_notifications
    sched.add_job(
        job_send_notifications,
        "interval",
        seconds=settings.sched_sender_seconds,
        id="sender_job",
        replace_existing=True
    )

    # Admin monitor (erro/bloqueio -> alerta no Telegram)
    if getattr(settings, "admin_monitor_enabled", True):
        from app.scheduler.admin_monitor_job import job_admin_monitor
        sched.add_job(
            job_admin_monitor,
            "interval",
            seconds=int(getattr(settings, "admin_monitor_seconds", 60) or 60),
            id="admin_monitor",
            replace_existing=True,
        )

    # Limpeza leve: mantém notifications enxutas (evita crescimento infinito)
    from app.scheduler.cleanup_job import job_cleanup_notifications
    sched.add_job(
        job_cleanup_notifications,
        "interval",
        hours=24,
        id="cleanup_notifications",
    )

    # Warm up Playwright worker thread (cheap) to reduce first-cold-start latency.
    if getattr(settings, "enable_playwright", False) and getattr(settings, "playwright_warmup_on_start", False):
        try:
            from app.services.playwright_pool import get_playwright_pool
            get_playwright_pool().start()
        except Exception:
            pass

    sched.start()
    return sched
