from typing import List
import time

from sqlalchemy.orm import Session

from app.core.settings import settings
from app.models.car_listing import CarListing
from app.scrapers.base import FetchBlocked
from app.sources import list_sources
from app.services.listings_service import ingest_listings
from app.services.source_backoff_service import is_source_allowed, mark_blocked, mark_error, mark_success
from app.services.source_configs_service import ensure_source_configs, get_source_config, build_scrape_context
from app.services.source_runs_service import record_run
from app.services.system_logs_service import log


def manual_search(db: Session, query: str, limit: int = 5) -> List[CarListing]:
    # Ensure configs exist (seed defaults once)
    ensure_source_configs(db)

    # Pluggable sources: iterate registry
    for plugin in list_sources():
        if not plugin.supports_manual_search:
            continue
        if plugin.scrape is None:
            continue

        cfg = get_source_config(db, plugin.name)
        if cfg and not bool(cfg.is_enabled):
            continue

        # Browser sources require Playwright (or forced browser via DB)
        if (plugin.fetch_mode == "browser" or (cfg and bool(cfg.force_browser))) and not settings.enable_playwright:
            record_run(db, source=plugin.name, kind="manual", status="skipped", payload={"reason": "playwright_off"})
            continue

        avail = is_source_allowed(db, plugin.name)
        if not avail.is_allowed:
            continue

        url = plugin.build_url(query)
        cooldown = int(cfg.cooldown_minutes or 0) if cfg else 0
        rate_limit_seconds = int(cfg.rate_limit_seconds or 0) if cfg else 0

        t0 = time.perf_counter()
        try:
            ctx = build_scrape_context(db, plugin.name)
            items = plugin.scrape(url, ctx)
            inserted_ids = ingest_listings(db, items)

            mark_success(
                db,
                plugin.name,
                rate_limit_seconds=rate_limit_seconds,
                payload={"manual_query": query, "inserted": len(inserted_ids or [])},
            )
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
            minutes = mark_blocked(
                db,
                plugin.name,
                base_cooldown_minutes=max(cooldown, 1),
                http_status=getattr(e, "status_code", None),
                url=getattr(e, "url", url),
            )
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
            log(db, "warn", f"scraper_{plugin.name}", "source_blocked", {"status_code": getattr(e, "status_code", None), "url": getattr(e, "url", url), "backoff_minutes": minutes})
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

    for t in terms:
        q = q.filter((CarListing.title.ilike(f"%{t}%")) | (CarListing.location.ilike(f"%{t}%")))

    return q.order_by(CarListing.created_at.desc()).limit(limit).all()
