from typing import List
from sqlalchemy.orm import Session
from app.core.settings import settings

from app.services.system_logs_service import log
import time

from app.services.source_backoff_service import is_source_allowed, mark_blocked, mark_error, mark_success
from app.services.source_runs_service import record_run
from app.services.listings_service import ingest_listings

from app.models.car_listing import CarListing

from app.sources import list_sources
from app.scrapers.base import FetchBlocked
from app.services.source_proxy_service import get_source_proxy_server
from app.services.source_rate_limit_service import get_source_rate_limit_seconds
from app.sources.types import ScrapeContext


def manual_search(db: Session, query: str, limit: int = 5) -> List[CarListing]:
    # Pluggable sources: iterate registry
    for plugin in list_sources():
        if not plugin.supports_manual_search:
            continue
        if plugin.enabled_setting and not getattr(settings, plugin.enabled_setting, False):
            continue
        if plugin.scrape is None:
            continue

        if plugin.fetch_mode == 'browser' and not settings.enable_playwright:
            # keep it silent in user flow; metrics still track skip
            record_run(db, source=plugin.name, kind='manual', status='skipped', payload={'reason': 'playwright_off'})
            continue

        cooldown = 0
        if plugin.cooldown_minutes_setting:
            cooldown = int(getattr(settings, plugin.cooldown_minutes_setting, 0) or 0)

        avail = is_source_allowed(db, plugin.name)
        if not avail.is_allowed:
            continue

        url = plugin.build_url(query)

        t0 = time.perf_counter()
        try:
            ctx = ScrapeContext(source=plugin.name, proxy_server=get_source_proxy_server(plugin.name))
            items = plugin.scrape(url, ctx)
            inserted_ids = ingest_listings(db, items)

            mark_success(db, plugin.name, rate_limit_seconds=get_source_rate_limit_seconds(plugin.name), payload={"manual_query": query, "inserted": len(inserted_ids or [])})
            record_run(
                db,
                source=plugin.name,
                kind="manual",
                status="success",
                query=query,
                url=url,
                duration_ms=int((time.perf_counter() - t0) * 1000),
                items_found=len(items or []),
                items_ingested=len(inserted_ids or []),
            )
        except FetchBlocked as e:
            minutes = mark_blocked(db, plugin.name, base_cooldown_minutes=max(cooldown, 1), http_status=getattr(e, "status_code", None), url=getattr(e, "url", url))
            record_run(
                db,
                source=plugin.name,
                kind="manual",
                status="blocked",
                query=query,
                url=getattr(e, "url", url),
                http_status=getattr(e, "status_code", None),
                duration_ms=int((time.perf_counter() - t0) * 1000),
                error=f"blocked(backoff={minutes}m)",
            )
            log(db, "warn", f"scraper_{plugin.name}", "source_blocked", {"status_code": e.status_code, "url": e.url, "backoff_minutes": minutes})
        except Exception as e:
            err = str(e)
            minutes = mark_error(db, plugin.name, base_cooldown_minutes=max(cooldown, 1), error=err, url=url)
            record_run(
                db,
                source=plugin.name,
                kind="manual",
                status="error",
                query=query,
                url=url,
                duration_ms=int((time.perf_counter() - t0) * 1000),
                error=f"{err} (backoff={minutes}m)",
            )
            log(db, "error", f"scraper_{plugin.name}", "scrape_failed", {"error": err, "url": url, "backoff_minutes": minutes})

    db.commit()

    terms = [t for t in query.lower().split() if t]

    q = db.query(CarListing)

    # opcional: só coisas recentes (evita lixo antigo na busca manual)
    # q = q.filter(CarListing.created_at >= datetime.now(timezone.utc) - timedelta(hours=24))

    # match simples: todos os termos no título/location
    for t in terms:
        q = q.filter(
            (CarListing.title.ilike(f"%{t}%")) |
            (CarListing.location.ilike(f"%{t}%"))
        )

    return q.order_by(CarListing.created_at.desc()).limit(limit).all()