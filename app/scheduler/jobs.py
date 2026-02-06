from sqlalchemy.orm import Session

from app.scrapers.base import FetchBlocked

import traceback

from app.services.admin_programming_alerts import maybe_alert_programming_error

from app.services.system_logs_service import log
from app.services.telemetry_events_service import emit_event
from app.services.notifications_queue_service import queue_notifications_for_matches
from app.services.matching_service import match_listings_for_wishlist, match_listings_for_wishlists
from app.services.listings_service import ingest_listings
from app.scrapers.diagnostics import ScrapeDiagnostics, using_diagnostics

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
    listing_rows = db.query(CarListing.id).filter(CarListing.id.in_(new_listing_ids)).all()
    listing_ids = [row[0] for row in listing_rows]
    if not listing_ids:
        return

    wishlists = db.query(Wishlist).filter(Wishlist.is_active.is_(True)).all()
    if not wishlists:
        return

    wishlist_ids = [w.id for w in wishlists]
    existing = db.query(Notification.user_id, Notification.wishlist_id, Notification.car_listing_id).filter(
        Notification.wishlist_id.in_(wishlist_ids),
        Notification.car_listing_id.in_(listing_ids),
    ).all()
    existing_keys = {(row[0], row[1], row[2]) for row in existing}

    new_notifications = []
    for w in wishlists:
        for listing_id in listing_ids:
            key = (w.user_id, w.id, listing_id)
            if key in existing_keys:
                continue
            new_notifications.append(Notification(
                user_id=w.user_id,
                wishlist_id=w.id,
                car_listing_id=listing_id,
                status="queued",
            ))

    if new_notifications:
        db.add_all(new_notifications)

    log(db, "info", component, "queued notifications", {
        "queued": len(new_notifications),
        "listings": len(listing_ids),
        "wishlists": len(wishlists),
    })
    db.commit()


def scrape_ingest_match(db, job_name, scraper_fn, search_url, *, ctx, wishlist=None) -> dict:
    diag = ScrapeDiagnostics(source=getattr(ctx, "source", ""), url=search_url, kind=job_name)
    try:
        with using_diagnostics(diag):
            listings = scraper_fn(search_url, ctx)
    except FetchBlocked as e:
        status_code = getattr(e, "status_code", None)
        url = getattr(e, "url", search_url)
        emit_event(db, level="warn", event_type="source_blocked", source=ctx.source, message="source_blocked", evidence={"status_code": status_code, "url": url}, tags=["blocked"])
        log(db, "warn", job_name, "source_blocked", {"status_code": status_code, "url": url}, source=ctx.source, event_type="source_blocked", tags=["blocked"])
        if status_code is not None:
            diag.note("blocked_status_code", status_code)
        diag.flag("blocked", True)
        return {"ok": False, "reason": "blocked", "status_code": status_code, "url": url, "diag": diag.snapshot()}
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
        diag.note("error", err)
        return {
            "ok": False,
            "reason": "error",
            "error": err,
            "url": search_url,
            "exc_type": exc_type,
            "is_bug": _is_bug_type(exc_type),
            "diag": diag.snapshot(),
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

    # High-level counters (helpful for /admin sources verbose)
    diag.inc("found", found)
    diag.inc("inserted", inserted)
    diag.inc("matched", matched)
    diag.inc("queued", queued)

    return {"ok": True, "found": found, "inserted": inserted, "matched": matched, "queued": queued, "diag": diag.snapshot()}


def scrape_ingest_match_many(db, job_name, scraper_fn, search_url, *, ctx, wishlists: list[Wishlist]) -> dict:
    """Scrape once, ingest once, then match+queue for many wishlists.

    This collapses duplicate work when multiple users share the same query/URL for a given source.
    """
    diag = ScrapeDiagnostics(source=getattr(ctx, "source", ""), url=search_url, kind=job_name)
    try:
        with using_diagnostics(diag):
            listings = scraper_fn(search_url, ctx)
    except FetchBlocked as e:
        status_code = getattr(e, "status_code", None)
        url = getattr(e, "url", search_url)
        emit_event(db, level="warn", event_type="source_blocked", source=ctx.source, message="source_blocked", evidence={"status_code": status_code, "url": url}, tags=["blocked"])
        log(db, "warn", job_name, "source_blocked", {"status_code": status_code, "url": url}, source=ctx.source, event_type="source_blocked", tags=["blocked"])
        if status_code is not None:
            diag.note("blocked_status_code", status_code)
        diag.flag("blocked", True)
        return {"ok": False, "reason": "blocked", "status_code": status_code, "url": url, "diag": diag.snapshot()}
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
        diag.note("error", err)
        return {
            "ok": False,
            "reason": "error",
            "error": err,
            "url": search_url,
            "exc_type": exc_type,
            "is_bug": _is_bug_type(exc_type),
            "diag": diag.snapshot(),
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

    diag.inc("found", found)
    diag.inc("inserted", inserted)
    diag.inc("matched", total_matched)
    diag.inc("queued", total_queued)
    diag.inc("wishlists", len(wishlists or []))

    return {"ok": True, "found": found, "inserted": inserted, "matched": total_matched, "queued": total_queued, "wishlists": len(wishlists or []), "diag": diag.snapshot()}
