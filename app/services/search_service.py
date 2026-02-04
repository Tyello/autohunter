import time
from typing import List, Optional

from sqlalchemy.orm import Session

from app.core.settings import settings
from app.models.car_listing import CarListing
from app.scrapers.base import FetchBlocked
from app.sources import list_sources
from app.services.listings_service import ingest_listings
from app.services.source_backoff_service import is_source_allowed, mark_blocked, mark_error, mark_success, mark_skipped
from app.services.source_configs_service import ensure_source_configs, get_source_config, build_scrape_context
from app.services.source_runs_service import record_run
from app.services.system_logs_service import log


def _duration_ms(start: float) -> int:
    return int((time.perf_counter() - start) * 1000)


def manual_search(db: Session, query: str, limit: int = 5, sources: Optional[List[str]] = None, *, force_scrape: bool = False) -> List[CarListing]:
    # Ensure configs exist (seed defaults once)
    ensure_source_configs(db)

    sources_norm = [s.strip().lower() for s in sources] if sources else None

    # Pluggable sources: iterate registry
    for plugin in list_sources():
        if sources_norm is not None and plugin.name.lower() not in sources_norm:
            continue
        if not plugin.supports_manual_search:
            continue
        if plugin.scrape is None:
            continue

        cfg = get_source_config(db, plugin.name)
        if cfg and not bool(cfg.is_enabled):
            record_run(db, source=plugin.name, kind="manual", status="skipped", query=query, url=plugin.build_url(query), error="disabled", payload={"reason": "disabled"})
            try:
                mark_skipped(db, plugin.name, reason="disabled", payload={"manual_query": query})
            except Exception:
                pass
            continue

        # Browser sources require Playwright (or forced browser via DB)
        if (plugin.fetch_mode == "browser" or (cfg and bool(cfg.force_browser))) and not settings.enable_playwright:
            record_run(db, source=plugin.name, kind="manual", status="skipped", payload={"reason": "playwright_off"})
            continue

        avail = is_source_allowed(db, plugin.name)
        if not avail.is_allowed and not force_scrape:
            payload = {"reason": avail.reason or "backoff"}
            if getattr(avail, "next_allowed_at", None):
                try:
                    payload["next_allowed_at"] = avail.next_allowed_at.isoformat()
                except Exception:
                    pass
            record_run(db, source=plugin.name, kind="manual", status="skipped", query=query, url=plugin.build_url(query), error="backoff", payload=payload)
            try:
                mark_skipped(db, plugin.name, reason=avail.reason or "backoff", payload=payload)
            except Exception:
                pass
            continue
        forced_backoff = (not avail.is_allowed and force_scrape)

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
                payload={"manual_query": query, "inserted": len(inserted_ids or []), "forced_backoff": bool(forced_backoff)},
            )
            record_run(
                db,
                source=plugin.name,
                kind="manual",
                status="success",
                query=query,
                url=url,
                duration_ms=_duration_ms(t0),
                items_found=len(items or []),
                items_ingested=len(inserted_ids or []),
            )
        except FetchBlocked as e:
            err_url = getattr(e, "url", url)
            err_status = getattr(e, "status_code", None)
            minutes = mark_blocked(
                db,
                plugin.name,
                base_cooldown_minutes=max(cooldown, 1),
                http_status=err_status,
                url=err_url,
            )
            record_run(
                db,
                source=plugin.name,
                kind="manual",
                status="blocked",
                query=query,
                url=err_url,
                http_status=err_status,
                duration_ms=_duration_ms(t0),
                error=f"blocked(backoff={minutes}m)",
            )
            log(
                db,
                "warn",
                f"scraper_{plugin.name}",
                "source_blocked",
                {"status_code": err_status, "url": err_url, "backoff_minutes": minutes},
            )
        except Exception as e:
            err = str(e)
            # If Playwright is globally enabled but restricted by PLAYWRIGHT_SOURCES,
            # treat as a 'skipped' run (do not penalize source backoff).
            if "playwright disabled for source" in err.lower():
                record_run(
                    db,
                    source=plugin.name,
                    kind="manual",
                    status="skipped",
                    query=query,
                    url=url,
                    duration_ms=_duration_ms(t0),
                    error=err,
                    payload={"reason": "playwright_sources_restricted"},
                )
                continue

            minutes = mark_error(db, plugin.name, base_cooldown_minutes=max(cooldown, 1), error=err, url=url)
            record_run(
                db,
                source=plugin.name,
                kind="manual",
                status="error",
                query=query,
                url=url,
                duration_ms=_duration_ms(t0),
                error=f"{err} (backoff={minutes}m)",
            )
            log(
                db,
                "error",
                f"scraper_{plugin.name}",
                "scrape_failed",
                {"error": err, "url": url, "backoff_minutes": minutes},
            )

    db.commit()

    terms = [t for t in query.lower().split() if t]

    q = db.query(CarListing)

    if sources_norm:
        q = q.filter(CarListing.source.in_(sources_norm))

    for t in terms:
        q = q.filter((CarListing.title.ilike(f"%{t}%")) | (CarListing.location.ilike(f"%{t}%")))

    return q.order_by(CarListing.created_at.desc()).limit(limit).all()
