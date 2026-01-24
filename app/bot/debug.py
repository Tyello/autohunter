from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.wishlist import Wishlist
from app.models.car_listing import CarListing
from app.models.notification import Notification
from app.models.system_log import SystemLog
from app.models.wishlist_filter import WishlistFilter

from app.services.wishlist_sources_service import allowed_sources_for_wishlist
from app.services.source_availability_service import is_in_cooldown
from app.services.search_urls_service import ml_url, olx_url
from app.services.source_proxy_service import get_source_proxy_server
from app.sources.types import ScrapeContext
from app.scheduler.jobs import scrape_ingest_match
from app.scrapers.mercadolivre import scrape_mercadolivre
from app.scrapers.olx import scrape_olx

from app.core.settings import settings


def run_once_for_wishlist(db: Session, wishlist) -> dict:
    q = wishlist.query
    sources = allowed_sources_for_wishlist(db, wishlist.id)

    ml = ml_url(q)
    ml_res = None
    if "mercadolivre" in sources:
        ctx = ScrapeContext(source="mercadolivre", proxy_server=get_source_proxy_server("mercadolivre"))
        ml_res = scrape_ingest_match(
            db,
            "scraper_mercadolivre_debug",
            scrape_mercadolivre,
            ml,
            ctx=ctx,
            wishlist=wishlist,
        )

    olx = olx_url(q)
    olx_res = None
    olx_skipped = None

    if "olx" not in sources:
        olx_skipped = "filtered_out"
    elif not settings.enable_olx:
        olx_skipped = "disabled"
    elif is_in_cooldown(db, "olx", settings.olx_cooldown_minutes):
        olx_skipped = "cooldown"
    else:
        ctx = ScrapeContext(source="olx", proxy_server=get_source_proxy_server("olx"))
        olx_res = scrape_ingest_match(
            db,
            "scraper_olx_debug",
            scrape_olx,
            olx,
            ctx=ctx,
            wishlist=wishlist,
        )

    return {
        "ok": True,
        "query": q,
        "sources": sorted(list(sources)),
        "ml_url": ml,
        "olx_url": olx,
        "ml_result": ml_res,
        "olx_result": olx_res,
        "olx_skipped": olx_skipped,
    }


def status_for_wishlist(db: Session, wishlist: Wishlist) -> dict:
    # filtros
    filters = db.query(WishlistFilter).filter(WishlistFilter.wishlist_id == wishlist.id).all()

    # notifications por status (da wishlist)
    by_status = (
        db.query(Notification.status, func.count(Notification.id))
        .filter(Notification.wishlist_id == wishlist.id)
        .group_by(Notification.status)
        .all()
    )
    status_counts = {s: c for s, c in by_status}

    # últimos 10 anúncios do DB (não necessariamente da wishlist, mas ajuda)
    listings = (
        db.query(CarListing)
        .order_by(CarListing.created_at.desc())
        .limit(10)
        .all()
    )

    # dedupe check (nunca pode existir)
    dupes = (
        db.query(CarListing.source, CarListing.external_id, func.count(CarListing.id).label("cnt"))
        .group_by(CarListing.source, CarListing.external_id)
        .having(func.count(CarListing.id) > 1)
        .limit(5)
        .all()
    )

    # últimos logs
    logs = (
        db.query(SystemLog)
        .order_by(SystemLog.created_at.desc())
        .limit(10)
        .all()
    )

    return {
        "wishlist": {"id": str(wishlist.id), "query": wishlist.query, "is_active": wishlist.is_active},
        "filters": [{"field": f.field, "operator": f.operator, "value": f.value} for f in filters],
        "notifications": status_counts,
        "last_listings": [{
            "source": x.source,
            "price": str(x.price) if x.price is not None else None,
            "title": (x.title or "")[:60],
            "url": x.url,
        } for x in listings],
        "dupes": [{"source": d[0], "external_id": d[1], "cnt": d[2]} for d in dupes],
        "last_logs": [{
            "level": l.level,
            "component": l.component,
            "message": l.message,
        } for l in logs],
    }
