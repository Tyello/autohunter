from apscheduler.schedulers.background import BackgroundScheduler

from app.db.session import SessionLocal
from app.services.system_logs_service import log
from app.services.search_urls_service import ml_url, olx_url
from app.scheduler.jobs import scrape_ingest_match

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
                if source_name == "mercadolivre":
                    url = ml_url(w.query)
                    scrape_ingest_match(db, "scraper_mercadolivre", scrape_mercadolivre, url)
                elif source_name == "olx":
                    url = olx_url(w.query)
                    scrape_ingest_match(db, "scraper_olx", scrape_olx, url)

        except Exception as e:
            log(db, "error", f"scheduler_{source_name}", "job failed", {"error": str(e)})


def start_scheduler() -> BackgroundScheduler:
    sched = BackgroundScheduler(timezone="UTC")

    # 30/30 min por fonte
    sched.add_job(lambda: job_run_source_for_all_wishlists("mercadolivre"), "interval", minutes=30, id="ml_30m")
    sched.add_job(lambda: job_run_source_for_all_wishlists("olx"), "interval", minutes=30, id="olx_30m")

    # sender a cada 1 min (usa a versão corrigida com daily_limit -> failed)
    from app.scheduler.sender_job import job_send_notifications
    sched.add_job(job_send_notifications, "interval", minutes=1, id="send_1m")

    sched.start()
    return sched
