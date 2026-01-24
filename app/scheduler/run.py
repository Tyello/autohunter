from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.executors.pool import ThreadPoolExecutor

from app.core.settings import settings

from app.db.session import SessionLocal

import time
import random

from app.services.system_logs_service import log
from app.services.source_backoff_service import is_source_allowed, mark_blocked, mark_error, mark_success, mark_skipped
from app.services.source_runs_service import record_run
from app.sources import list_sources
from app.services.wishlist_sources_service import allowed_sources_for_wishlist
from app.services.source_proxy_service import get_source_proxy_server
from app.services.source_rate_limit_service import get_source_rate_limit_seconds
from app.sources.types import ScrapeContext

from app.scheduler.jobs import scrape_ingest_match
from app.scheduler.heartbeat import heartbeat

from app.models.wishlist import Wishlist


def job_run_source_for_all_wishlists(source_name: str):
    with SessionLocal() as db:
        try:
            component = f"scheduler_{source_name}"
            log(db, "info", component, "job tick")

            wishlists = db.query(Wishlist).filter(Wishlist.is_active == True).all()
            if not wishlists:
                log(db, "info", component, "no active wishlists")
                return

            plugin = next((p for p in list_sources() if p.name == source_name), None)
            if plugin is None:
                log(db, "error", component, "unknown_source", {"source": source_name})
                return

            # Global checks (per-source)
            # Browser sources require Playwright
            if plugin.fetch_mode == 'browser' and not settings.enable_playwright:
                mark_skipped(db, plugin.name, 'playwright_off')
                record_run(db, source=plugin.name, kind='scheduler', status='skipped', payload={'reason': 'playwright_off'})
                db.commit()
                log(db, 'warn', component, 'playwright_off')
                return


            if plugin.enabled_setting and not getattr(settings, plugin.enabled_setting, False):
                mark_skipped(db, plugin.name, "disabled", {"enabled_setting": plugin.enabled_setting})
                record_run(db, source=plugin.name, kind="scheduler", status="skipped", payload={"reason": "disabled"})
                db.commit()
                return

            cooldown = 0
            if plugin.cooldown_minutes_setting:
                cooldown = int(getattr(settings, plugin.cooldown_minutes_setting, 0) or 0)

            avail = is_source_allowed(db, plugin.name)
            if not avail.is_allowed:
                mark_skipped(db, plugin.name, "backoff", {"next_allowed_at": str(avail.next_allowed_at) if avail.next_allowed_at else None})
                record_run(db, source=plugin.name, kind="scheduler", status="skipped", payload={"reason": "backoff", "next_allowed_at": str(avail.next_allowed_at) if avail.next_allowed_at else None})
                db.commit()
                log(db, "info", component, "skipped_backoff", {"next_allowed_at": str(avail.next_allowed_at) if avail.next_allowed_at else None})
                return

            if plugin.scrape is None:
                mark_skipped(db, plugin.name, "not_implemented")
                record_run(db, source=plugin.name, kind="scheduler", status="skipped", payload={"reason": "not_implemented"})
                db.commit()
                log(db, "warn", component, "not_implemented")
                return

            t0 = time.perf_counter()
            total_found = 0
            total_inserted = 0
            total_matched = 0
            total_queued = 0
            ran_any = False
            final_status = "success"
            final_http_status = None
            final_error = None

            for w in wishlists:
                sources = allowed_sources_for_wishlist(db, w.id)

                if plugin.name not in sources:
                    log(db, "info", component, "skipped_filtered_out", {"wishlist_id": str(w.id), "source": plugin.name})
                    continue

                # enabled/backoff são globais por fonte e já foram checados acima

                url = plugin.build_url(w.query)
                log(db, "info", component, "job_started", {"wishlist_id": str(w.id), "query": w.query, "url": url})

                ran_any = True
                ctx = ScrapeContext(source=plugin.name, proxy_server=get_source_proxy_server(plugin.name))
                res = scrape_ingest_match(db, component, plugin.scrape, url, ctx=ctx, wishlist=w)

                if res.get("ok") is True:
                    total_found += int(res.get("found") or 0)
                    total_inserted += int(res.get("inserted") or 0)
                    total_matched += int(res.get("matched") or 0)
                    total_queued += int(res.get("queued") or 0)
                else:
                    reason = res.get("reason")
                    if reason == "blocked":
                        final_status = "blocked"
                        final_http_status = res.get("status_code")
                        minutes = mark_blocked(db, plugin.name, base_cooldown_minutes=max(cooldown, 1), http_status=final_http_status, url=res.get("url"))
                        final_error = f"blocked(backoff={minutes}m)"
                        log(db, "warn", component, "backoff_applied", {"source": plugin.name, "minutes": minutes})
                        break
                    else:
                        final_status = "error"
                        final_error = res.get("error") or "scrape_failed"
                        minutes = mark_error(db, plugin.name, base_cooldown_minutes=max(cooldown, 1), error=final_error, url=res.get("url"))
                        log(db, "error", component, "backoff_applied", {"source": plugin.name, "minutes": minutes, "error": final_error})
                        break

                log(db, "info", component, "job_finished", {"wishlist_id": str(w.id), "query": w.query, "result": res})

                # Evita "rajada" no mesmo tick do scheduler (sinal forte de bot em fontes sensíveis).
                # Para OLX especificamente, adiciona um pacing humano entre wishlists.
                if plugin.name == "olx":
                    time.sleep(random.randint(8, 25))

            duration_ms = int((time.perf_counter() - t0) * 1000)

            if not ran_any:
                final_status = "skipped"
                mark_skipped(db, plugin.name, "no_work")
            elif final_status == "success":
                mark_success(db, plugin.name, rate_limit_seconds=get_source_rate_limit_seconds(plugin.name), payload={
                    "found": total_found,
                    "inserted": total_inserted,
                    "matched": total_matched,
                    "queued": total_queued,
                    "duration_ms": duration_ms,
                })

            record_run(
                db,
                source=plugin.name,
                kind="scheduler",
                status=final_status,
                duration_ms=duration_ms,
                http_status=final_http_status,
                items_found=total_found if ran_any else None,
                items_ingested=total_inserted if ran_any else None,
                items_matched=total_matched if ran_any else None,
                notifications_queued=total_queued if ran_any else None,
                error=final_error,
            )

            db.commit()


        except Exception as e:
            log(db, "error", f"scheduler_{source_name}", "job failed", {"error": str(e)})


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

    # Pluggable sources: schedule every registered plugin that declares an interval.
    # This keeps scaling sources O(1): add plugin -> scheduler picks it up.
    for plugin in list_sources():
        if not plugin.supports_wishlist_monitoring:
            continue
        if not plugin.sched_minutes_setting:
            continue

        minutes = int(getattr(settings, plugin.sched_minutes_setting, 0) or 0)
        if minutes <= 0:
            # allow disabling a job by setting interval to 0
            continue

        job_id = f"{plugin.name}_job"
        sched.add_job(
            lambda n=plugin.name: job_run_source_for_all_wishlists(n),
            "interval",
            minutes=minutes,
            id=job_id,
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

    # Limpeza leve: mantém notifications enxutas (evita crescimento infinito)
    from app.scheduler.cleanup_job import job_cleanup_notifications
    sched.add_job(
        job_cleanup_notifications,
        "interval",
        hours=24,
        id="cleanup_notifications",
    )

    sched.start()
    return sched
