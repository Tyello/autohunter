from sqlalchemy.orm import Session

from app.scrapers.base import FetchBlocked

import traceback

from app.services.admin_programming_alerts import maybe_alert_programming_error

from app.services.system_logs_service import log
from app.services.telemetry_events_service import emit_event
from app.services.notifications_service import create_queued
from app.services.notifications_queue_service import queue_notifications_for_matches
from app.services.matching_service import match_listings_for_wishlist, match_listings_for_wishlists
from app.services.listings_service import ingest_listings

from app.models.wishlist import Wishlist
from app.models.car_listing import CarListing
from app.models.notification import Notification


def _is_bug_type(exc_type: str) -> bool:
    return exc_type in {
        "AttributeError",
        "ImportError",
        "ModuleNotFoundError",
        "SyntaxError",
        "NameError",
        "TypeError",
        "PlaywrightInitError",
    }



def queue_notifications_for_new_listings(db: Session, component: str, new_listing_ids: list):
    listings = db.query(CarListing).filter(CarListing.id.in_(new_listing_ids)).all()
    if not listings:
        return

    wishlists = db.query(Wishlist).filter(Wishlist.is_active == True).all()

    queued = 0
    for w in wishlists:
        for listing in listings:
            exists = (
                db.query(Notification.id)
                .filter(Notification.user_id == w.user_id)
                .filter(Notification.wishlist_id == w.id)
                .filter(Notification.car_listing_id == listing.id)
                .first()
            )
            if exists:
                continue

            create_queued(db, user_id=w.user_id, wishlist_id=w.id, car_listing_id=listing.id)
            queued += 1

    log(db, "info", component, "queued notifications", {"queued": queued, "listings": len(listings), "wishlists": len(wishlists)})
    db.commit()


def scrape_ingest_match(db, job_name, scraper_fn, search_url, *, ctx, wishlist=None) -> dict:
    try:
        listings = scraper_fn(search_url, ctx)
    except FetchBlocked as e:
        status_code = getattr(e, "status_code", None)
        url = getattr(e, "url", search_url)
        emit_event(db, level="warn", event_type="source_blocked", source=ctx.source, message="source_blocked", evidence={"status_code": status_code, "url": url}, tags=["blocked"])
        log(db, "warn", job_name, "source_blocked", {"status_code": status_code, "url": url}, source=ctx.source, event_type="source_blocked", tags=["blocked"])
        return {"ok": False, "reason": "blocked", "status_code": status_code, "url": url}
    except Exception as e:
        exc_type = type(e).__name__
        err = f"{exc_type}: {e}"
        tb = traceback.format_exc(limit=6)
        emit_event(db, level="error", event_type="scrape_failed", source=ctx.source, message="scrape_failed", evidence={"error": err, "url": search_url, "exc_type": exc_type}, tags=["error"])
        log(db, "error", job_name, "scrape_failed", {"error": err, "url": search_url, "tb": tb}, source=ctx.source, event_type="scrape_failed", tags=["error"])
        # alerta só admins (throttled) quando for erro de programação
        try:
            maybe_alert_programming_error(job_name, e, url=search_url)
        except Exception:
            pass
        return {
            "ok": False,
            "reason": "error",
            "error": err,
            "url": search_url,
            "exc_type": exc_type,
            "is_bug": _is_bug_type(exc_type),
        }

    found = len(listings or [])

    inserted_ids = ingest_listings(db, listings)
    inserted = len(inserted_ids or [])

    matched = 0
    queued = 0

    if wishlist is not None and inserted_ids:
        matched_listings = match_listings_for_wishlist(db, wishlist, inserted_ids)
        matched = len(matched_listings)
        if matched:
            queued = queue_notifications_for_matches(db, wishlist, matched_listings)

    emit_event(db, level="info", event_type="pipeline_summary", source=ctx.source, message="pipeline_summary", evidence={
        "wishlist_id": str(getattr(wishlist, "id", "")) if wishlist else None,
        "url": search_url,
        "found": found,
        "inserted": inserted,
        "matched": matched,
        "queued": queued,
    }, tags=["ok"])

    log(db, "info", job_name, "pipeline_summary", {
        "wishlist_id": str(getattr(wishlist, "id", "")) if wishlist else None,
        "url": search_url,
        "found": found,
        "inserted": inserted,
        "matched": matched,
        "queued": queued,
    }, source=ctx.source, event_type="pipeline_summary", tags=["ok"])

    db.commit()

    return {"ok": True, "found": found, "inserted": inserted, "matched": matched, "queued": queued}


def scrape_ingest_match_many(db, job_name, scraper_fn, search_url, *, ctx, wishlists: list[Wishlist]) -> dict:
    """Scrape once, ingest once, then match+queue for many wishlists.

    This collapses duplicate work when multiple users share the same query/URL for a given source.
    """
    try:
        listings = scraper_fn(search_url, ctx)
    except FetchBlocked as e:
        status_code = getattr(e, "status_code", None)
        url = getattr(e, "url", search_url)
        emit_event(db, level="warn", event_type="source_blocked", source=ctx.source, message="source_blocked", evidence={"status_code": status_code, "url": url}, tags=["blocked"])
        log(db, "warn", job_name, "source_blocked", {"status_code": status_code, "url": url}, source=ctx.source, event_type="source_blocked", tags=["blocked"])
        return {"ok": False, "reason": "blocked", "status_code": status_code, "url": url}
    except Exception as e:
        exc_type = type(e).__name__
        err = f"{exc_type}: {e}"
        tb = traceback.format_exc(limit=6)
        emit_event(db, level="error", event_type="scrape_failed", source=ctx.source, message="scrape_failed", evidence={"error": err, "url": search_url, "exc_type": exc_type}, tags=["error"])
        log(db, "error", job_name, "scrape_failed", {"error": err, "url": search_url, "tb": tb}, source=ctx.source, event_type="scrape_failed", tags=["error"])
        # alerta só admins (throttled) quando for erro de programação
        try:
            maybe_alert_programming_error(job_name, e, url=search_url)
        except Exception:
            pass
        return {
            "ok": False,
            "reason": "error",
            "error": err,
            "url": search_url,
            "exc_type": exc_type,
            "is_bug": _is_bug_type(exc_type),
        }

    found = len(listings or [])

    inserted_ids = ingest_listings(db, listings)
    inserted = len(inserted_ids or [])

    total_matched = 0
    total_queued = 0

    # Keep the semantics: only notify on NEW listings (inserted_ids).
    if inserted_ids and wishlists:
        new_listings = db.query(CarListing).filter(CarListing.id.in_(list(inserted_ids))).all()
        matches_by_wishlist = match_listings_for_wishlists(wishlists, new_listings)

        for w in wishlists:
            matched_listings = matches_by_wishlist.get(w.id) or []
            m = len(matched_listings)
            if not m:
                continue
            total_matched += m
            total_queued += int(queue_notifications_for_matches(db, w, matched_listings) or 0)

    emit_event(db, level="info", event_type="pipeline_summary_many", source=ctx.source, message="pipeline_summary_many", evidence={
        "url": search_url,
        "wishlists": len(wishlists or []),
        "found": found,
        "inserted": inserted,
        "matched": total_matched,
        "queued": total_queued,
    }, tags=["ok"])

    log(db, "info", job_name, "pipeline_summary_many", {
        "url": search_url,
        "wishlists": len(wishlists or []),
        "found": found,
        "inserted": inserted,
        "matched": total_matched,
        "queued": total_queued,
    }, source=ctx.source, event_type="pipeline_summary_many", tags=["ok"])

    db.commit()

    return {"ok": True, "found": found, "inserted": inserted, "matched": total_matched, "queued": total_queued, "wishlists": len(wishlists or [])}
