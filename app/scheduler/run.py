from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.executors.pool import ThreadPoolExecutor
from zoneinfo import ZoneInfo

import threading
from datetime import datetime, timezone, timedelta

from app.core.settings import settings
from app.core.shutdown import is_shutdown_requested
from app.db.session import SessionLocal
from app.sources import list_sources
from app.scheduler.heartbeat import heartbeat

from app.services.system_logs_service import log
from app.services.source_backoff_service import mark_skipped
from app.services.source_runs_service import record_run
from sqlalchemy import select

from app.models.source_config import SourceConfig
from app.models.source_state import SourceState
from app.services.source_execution_service import run_source_for_all_wishlists as _exec_source_for_all_wishlists
from app.services.source_backoff_service import is_source_allowed
from app.services.source_configs_service import ensure_source_configs
from app.services.scrape_jobs_service import enqueue_job, count_active_jobs
from app.sources.registry import get_source


_last_heartbeat_error_log_at: datetime | None = None


def _utcnow():
    return datetime.now(timezone.utc)


def _log_suppressed_exception(*, stage: str, exc: Exception, impact: str, fallback: str, worker: str | None = None) -> None:
    worker_label = worker or "scheduler"
    try:
        with SessionLocal() as db:
            log(
                db,
                "warn",
                worker_label,
                "suppressed_exception",
                {
                    "stage": stage,
                    "exc_type": type(exc).__name__,
                    "message": str(exc)[:280],
                    "impact": impact,
                    "fallback": fallback,
                },
            )
            db.commit()
    except Exception:
        return


def _get_cfg(db, source: str):
    return db.execute(select(SourceConfig).where(SourceConfig.source == source)).scalar_one_or_none()


def _get_state(db, source: str):
    return db.execute(select(SourceState).where(SourceState.source == source)).scalar_one_or_none()


def _print_throttled_scheduler_error(stage: str, exc: Exception) -> None:
    global _last_heartbeat_error_log_at
    now = _utcnow()
    if _last_heartbeat_error_log_at and now - _last_heartbeat_error_log_at < timedelta(minutes=1):
        return
    _last_heartbeat_error_log_at = now
    print(
        "[scheduler] "
        f"{stage}_failed exc_type={type(exc).__name__} message={str(exc)[:300]} "
        "hint='check DATABASE_URL and run alembic upgrade head'",
        flush=True,
    )


def job_heartbeat():
    if is_shutdown_requested():
        return
    db = SessionLocal()
    try:
        heartbeat(db)
        db.commit()
    except Exception as exc:
        try:
            db.rollback()
        except Exception:
            pass
        _print_throttled_scheduler_error("heartbeat", exc)
    finally:
        db.close()


def job_run_source_for_all_wishlists(source_name: str):
    """Scheduler tick for one source.

    **Mudanca chave**: fontes browser/Playwright agora entram em uma *fila* persistente
    (scrape_jobs) para execucao em ordem (FIFO). Isso elimina "skipped:parallel_limit"
    e garante previsibilidade.

    Fontes HTTP tambem entram em fila persistente ('http'). Execucao pesada sai do tick e vai para workers, garantindo fairness e paralelismo controlado.
    """
    if is_shutdown_requested():
        return

    src = (source_name or "").lower().strip()
    plugin = get_source(src)
    if not plugin:
        return

    with SessionLocal() as db:
        try:
            ensure_source_configs(db)
            cfg = _get_cfg(db, src)
            if not cfg or not bool(cfg.is_enabled) or plugin.scrape is None:
                db.commit()
                return

            is_browser = (plugin.fetch_mode == "browser") or bool(cfg.force_browser)

            # Browser-first: enqueue FIFO
            if is_browser:
                if not bool(getattr(settings, "enable_playwright", False)):
                    mark_skipped(db, src, "playwright_off")
                    record_run(db, source=src, kind="scheduler", status="skipped", payload={"reason": "playwright_off"})
                    db.commit()
                    return

                minutes = int(cfg.sched_minutes or 0)
                if minutes <= 0:
                    db.commit()
                    return

                st = _get_state(db, src)
                last_eff = st.last_effective_run_at if st else None
                next_due = (last_eff + timedelta(minutes=minutes)) if last_eff else _utcnow()
                if _utcnow() < next_due:
                    db.commit()
                    return

                avail = is_source_allowed(db, src)
                if not avail.is_allowed:
                    # nao marca skip aqui para nao poluir; o backoff ja esta no state
                    db.commit()
                    return

                inserted = enqueue_job(db, source=src, queue="browser", run_at=next_due, priority=0, max_attempts=3)
                if not inserted:
                    # fila cheia (cap) ou job ja ativo. Se estiver cheia, registra evidencia.
                    cap = int(getattr(settings, "playwright_queue_max_jobs", 25) or 25)
                    if cap > 0 and count_active_jobs(db, queue="browser") >= cap:
                        mark_skipped(db, src, "queue_full", {"cap": cap})
                        record_run(db, source=src, kind="scheduler", status="skipped", payload={"reason": "queue_full", "cap": cap})
                db.commit()
                return

            # HTTP: enqueue FIFO (mesma filosofia do browser)
            minutes = int(cfg.sched_minutes or 0)
            if minutes <= 0:
                db.commit()
                return

            st = _get_state(db, src)
            last_eff = st.last_effective_run_at if st else None
            next_due = (last_eff + timedelta(minutes=minutes)) if last_eff else _utcnow()
            if _utcnow() < next_due:
                db.commit()
                return

            avail = is_source_allowed(db, src)
            if not avail.is_allowed:
                # evidencia para admin (evita "sumir" sem motivo)
                mark_skipped(db, src, "backoff", {"until": getattr(avail, "until", None), "reason": getattr(avail, "reason", None)})
                record_run(db, source=src, kind="scheduler", status="skipped", payload={"reason": "backoff", "until": getattr(avail, "until", None), "detail": getattr(avail, "reason", None)})
                db.commit()
                return

            inserted = enqueue_job(db, source=src, queue="http", run_at=next_due, priority=0, max_attempts=3)
            if not inserted:
                cap = int(getattr(settings, "http_queue_max_jobs", 200) or 200)
                if cap > 0 and count_active_jobs(db, queue="http") >= cap:
                    mark_skipped(db, src, "queue_full", {"cap": cap, "queue": "http"})
                    record_run(db, source=src, kind="scheduler", status="skipped", payload={"reason": "queue_full", "cap": cap, "queue": "http"})
            db.commit()
            return

        except Exception as e:
            try:
                log(db, "error", f"scheduler_{source_name}", "tick_failed", {"err": str(e)[:300]})
                db.commit()
            except Exception:
                pass


def start_scheduler() -> BackgroundScheduler:
    sched = BackgroundScheduler(
        timezone="UTC",
        executors={
            "default": ThreadPoolExecutor(int(getattr(settings, "scheduler_workers", 2) or 2)),
            "http": ThreadPoolExecutor(int(getattr(settings, "scheduler_http_workers", 3) or 3)),
            "browser": ThreadPoolExecutor(int(getattr(settings, "scheduler_browser_workers", 1) or 1)),
            "sender": ThreadPoolExecutor(int(getattr(settings, "scheduler_sender_workers", 1) or 1)),
        },
        job_defaults={
            "coalesce": True,
            "misfire_grace_time": 3600,
            "max_instances": 1,
        },
    )

    # Smoke test Playwright no boot (falha cedo em caso de bug/config/permissoes)
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
                    except Exception as alert_exc:
                        _log_suppressed_exception(
                            stage="bootstrap.playwright_smoke.alert",
                            exc=alert_exc,
                            impact="alert_not_sent",
                            fallback="scheduler_continues_without_admin_alert",
                            worker="boot",
                        )
        except Exception as boot_exc:
            # nunca deixa o scheduler morrer por causa do smoke
            _log_suppressed_exception(
                stage="bootstrap.playwright_smoke.import",
                exc=boot_exc,
                impact="smoke_check_skipped",
                fallback="scheduler_continues",
                worker="boot",
            )

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

    sched.add_job(job_heartbeat, "interval", seconds=10, id="heartbeat", replace_existing=True)

    # Browser queue worker: executa jobs Playwright em ordem (FIFO)
    try:
        from app.scheduler.browser_queue_job import job_browser_queue_worker

        worker_s = int(getattr(settings, "scheduler_browser_worker_seconds", 5) or 5)
        worker_s = max(2, min(worker_s, 60))
        sched.add_job(
            job_browser_queue_worker,
            "interval",
            seconds=worker_s,
            id="browser_queue_worker",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
            executor="browser",
        )
    except Exception as e:
        _log_suppressed_exception(
            stage="bootstrap.browser_queue_worker",
            exc=e,
            impact="browser_queue_worker_not_registered",
            fallback="scheduler_continues_without_browser_worker",
            worker="boot",
        )

    # HTTP queue workers: executa jobs HTTP em paralelo controlado
    try:
        from app.scheduler.http_queue_job import job_http_queue_worker

        worker_s = int(getattr(settings, "scheduler_http_worker_seconds", 2) or 2)
        worker_s = max(1, min(worker_s, 60))
        workers = int(getattr(settings, "scheduler_http_worker_count", 2) or 2)
        workers = max(1, min(workers, 8))

        for i in range(workers):
            wid = f"http_queue_worker_{i+1}"
            sched.add_job(
                lambda w=wid: job_http_queue_worker(w),
                "interval",
                seconds=worker_s,
                id=wid,
                replace_existing=True,
                max_instances=1,
                coalesce=True,
                executor="http",
            )
    except Exception as e:
        _log_suppressed_exception(
            stage="bootstrap.http_queue_worker",
            exc=e,
            impact="http_queue_workers_not_registered",
            fallback="scheduler_continues_without_http_workers",
            worker="boot",
        )

    from app.scheduler.sender_job import job_send_notifications
    from app.scheduler.auction_notification_job import job_scheduled_auction_notification
    from app.bot.sender import telegram_sender
    sched.add_job(
        job_send_notifications,
        "interval",
        seconds=settings.sched_sender_seconds,
        id="sender_job",
        replace_existing=True,
        executor="sender",
    )
    sched.add_job(
        lambda: job_scheduled_auction_notification(bot=telegram_sender),
        "interval",
        minutes=max(15, int(getattr(settings, "auction_notifications_scheduler_minutes", 60) or 60)),
        id="auction_notification_scheduler_job",
        replace_existing=True,
        executor="sender",
        max_instances=1,
        coalesce=True,
    )

    if bool(getattr(settings, "tracking_price_alerts_enabled", False)):
        from app.scheduler.tracking_alerts_job import job_tracking_price_alerts
        sched.add_job(
            job_tracking_price_alerts,
            "interval",
            minutes=max(5, int(getattr(settings, "tracking_price_alerts_interval_minutes", 60) or 60)),
            id="tracking_price_alerts_job",
            replace_existing=True,
            executor="sender",
        )

    # Digest semanal para usuários (sábado 10:00 no timezone padrão do produto)
    from app.scheduler.weekly_wishlist_digest_job import job_weekly_wishlist_digest
    sched.add_job(
        job_weekly_wishlist_digest,
        "cron",
        day_of_week="sat",
        hour=10,
        minute=0,
        timezone=ZoneInfo(getattr(settings, "default_user_timezone", "America/Sao_Paulo")),
        id="weekly_wishlist_digest",
        replace_existing=True,
        executor="sender",
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

    # Facebook session healthcheck
    try:
        from app.scheduler.jobs_fb_sessions import job_fb_sessions_healthcheck
        fb_hours = int(getattr(settings, "fb_healthcheck_hours", 6) or 6)
        fb_hours = max(1, min(fb_hours, 24))
        sched.add_job(
            job_fb_sessions_healthcheck,
            "interval",
            hours=fb_hours,
            id="fb_sessions_healthcheck",
            replace_existing=True,
            max_instances=1,
        )
    except Exception as e:
        _log_suppressed_exception(
            stage="bootstrap.fb_sessions_healthcheck",
            exc=e,
            impact="fb_healthcheck_not_registered",
            fallback="scheduler_continues_without_fb_healthcheck",
            worker="boot",
        )

    # Autopilot (detecta regressões/bloqueios e manda alertas compactos)
    if getattr(settings, "autopilot_enabled", True):
        from app.scheduler.autopilot_job import job_autopilot_scan, job_autopilot_daily_digest
        sched.add_job(
            job_autopilot_scan,
            "interval",
            seconds=int(getattr(settings, "autopilot_scan_seconds", 60) or 60),
            id="autopilot_scan",
            replace_existing=True,
        )

        # Digest diário (hora UTC configurável)
        if getattr(settings, "autopilot_daily_digest_enabled", True):
            h = int(getattr(settings, "autopilot_daily_digest_hour_utc", 12) or 12)
            h = max(0, min(h, 23))
            sched.add_job(
                job_autopilot_daily_digest,
                "cron",
                hour=h,
                minute=0,
                id="autopilot_daily_digest",
                replace_existing=True,
            )

    # Limpeza leve: mantem notifications enxutas (evita crescimento infinito) (evita crescimento infinito)
    from app.scheduler.cleanup_job import job_cleanup_notifications
    sched.add_job(
        job_cleanup_notifications,
        "interval",
        hours=24,
        id="cleanup_notifications",
    )
    from app.scheduler.filesystem_cleanup_job import job_filesystem_cleanup_daily
    sched.add_job(
        job_filesystem_cleanup_daily,
        "cron",
        hour=3,
        minute=0,
        id="filesystem_cleanup_daily",
        replace_existing=True,
    )
    from app.scheduler.premium_expiration_job import job_expire_premium_subscriptions
    sched.add_job(
        job_expire_premium_subscriptions,
        "cron",
        hour=12,
        minute=0,
        id="premium_expiration_daily",
        replace_existing=True,
    )

    # Warm up Playwright worker thread (cheap) to reduce first-cold-start latency.
    if getattr(settings, "enable_playwright", False) and getattr(settings, "playwright_warmup_on_start", False):
        try:
            from app.services.playwright_pool import get_playwright_pool
            get_playwright_pool().start()
        except Exception as e:
            _log_suppressed_exception(
                stage="bootstrap.playwright_warmup",
                exc=e,
                impact="warmup_skipped",
                fallback="lazy_playwright_start",
                worker="boot",
            )

    sched.start()
    return sched
