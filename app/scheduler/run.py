from apscheduler.schedulers.background import BackgroundScheduler

from app.core.settings import settings

from app.db.session import SessionLocal

from app.services.system_logs_service import log
from app.services.search_urls_service import ml_url, olx_url
from app.services.wishlist_sources_service import allowed_sources_for_wishlist
from app.services.source_availability_service import is_in_cooldown

from app.scheduler.jobs import scrape_ingest_match
from app.scheduler.heartbeat import heartbeat

from app.scrapers.mercadolivre import scrape_mercadolivre
from app.scrapers.olx import scrape_olx

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

            for w in wishlists:
                sources = allowed_sources_for_wishlist(db, w.id)

                if source_name == "mercadolivre":
                    if "mercadolivre" not in sources:
                        log(db, "info", component, "skipped_filtered_out",
                            {"wishlist_id": str(w.id), "source": "mercadolivre"})
                        continue

                    url = ml_url(w.query)
                    scrape_ingest_match(db, "scraper_mercadolivre", scrape_mercadolivre, url)

                elif source_name == "olx":
                    if "olx" not in sources:
                        log(db, "info", component, "skipped_filtered_out", {"wishlist_id": str(w.id), "source": "olx"})
                        continue

                    if not settings.enable_olx:
                        log(db, "info", component, "skipped_disabled", {"source": "olx"})
                        continue

                    if is_in_cooldown(db, "olx", settings.olx_cooldown_minutes):
                        log(db, "info", component, "skipped_cooldown", {"source": "olx"})
                        continue

                    url = olx_url(w.query)
                    log(db, "info", component, "job_started", {"wishlist_id": str(w.id), "query": w.query, "url": url})

                    res = scrape_ingest_match(db, component, scrape_olx, url, wishlist=w)

                    log(db, "info", component, "job_finished", {
                        "wishlist_id": str(w.id),
                        "query": w.query,
                        "result": res,
                    })


        except Exception as e:
            log(db, "error", f"scheduler_{source_name}", "job failed", {"error": str(e)})


def start_scheduler() -> BackgroundScheduler:
    sched = BackgroundScheduler(timezone="UTC")

    sched.add_job(
        lambda: job_run_source_for_all_wishlists("mercadolivre"),
        "interval",
        minutes=settings.sched_ml_minutes,
        id="ml_job",
    )

    sched.add_job(
        lambda: job_run_source_for_all_wishlists("olx"),
        "interval",
        minutes=settings.sched_olx_minutes,
        id="olx_job",
    )

    def _job_heartbeat():
        db = SessionLocal()
        try:
            heartbeat(db)
            db.commit()
        finally:
            db.close()

    sched.add_job(_job_heartbeat, "interval", seconds=10, id="heartbeat")

    from app.scheduler.sender_job import job_send_notifications
    sched.add_job(
        job_send_notifications,
        "interval",
        seconds=settings.sched_sender_seconds,
        id="sender_job",
    )

    sched.start()
    return sched
