from sqlalchemy.orm import Session

from app.scrapers.base import FetchBlocked

import traceback

from app.services.admin_programming_alerts import maybe_alert_programming_error

from app.services.system_logs_service import log
from app.services.telemetry_events_service import emit_event
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





def _ctx_fetch_diag(ctx) -> dict:
    return {
        "hybrid_browser_used": bool(getattr(ctx, "_hybrid_browser_used", False)),
        "hybrid_blocked": bool(getattr(ctx, "_hybrid_blocked", False)),
        "hybrid_blocked_status": getattr(ctx, "_hybrid_blocked_status", None),
    }


def _resolve_candidate_listings(
    db: Session,
    *,
    source: str,
    scraped: list,
    inserted_ids: list | None = None,
    limit: int = 250,
) -> list[CarListing]:
    """Resolve scraped dicts -> persisted CarListing rows.

    We intentionally match/notify based on what the scraper *returned now*, even
    if the listing was already in DB (e.g., user created wishlist after it was
    first ingested). Dedupe is handled downstream by notifications table.
    """

    src = (source or "").strip().lower()
    ext_ids: list[str] = []

    for it in (scraped or []):
        if not isinstance(it, dict):
            continue
        it_src = (it.get("source") or src).strip().lower()
        if it_src != src:
            continue
        eid = it.get("external_id")
        if eid is None:
            continue
        s = str(eid).strip()
        if s:
            ext_ids.append(s)

    # dedupe preserving order
    ext_ids = list(dict.fromkeys(ext_ids))[: max(int(limit), 1)]

    rows: list[CarListing] = []
    if ext_ids:
        rows.extend(
            db.query(CarListing)
            .filter(CarListing.source == src)
            .filter(CarListing.external_id.in_(ext_ids))
            .all()
        )

    if inserted_ids:
        rows.extend(db.query(CarListing).filter(CarListing.id.in_(list(inserted_ids))).all())

    # final dedupe by id preserving order
    seen = set()
    out: list[CarListing] = []
    for r in rows:
        if not getattr(r, "id", None):
            continue
        if r.id in seen:
            continue
        seen.add(r.id)
        out.append(r)
    return out

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
    try:
        listings = scraper_fn(search_url, ctx)
    except FetchBlocked as e:
        status_code = getattr(e, "status_code", None)
        url = getattr(e, "url", search_url)
        emit_event(db, level="warn", event_type="source_blocked", source=ctx.source, message="source_blocked", evidence={"status_code": status_code, "url": url}, tags=["blocked"])
        log(db, "warn", job_name, "source_blocked", {"status_code": status_code, "url": url}, source=ctx.source, event_type="source_blocked", tags=["blocked"])
        return {"ok": False, "reason": "blocked", "status_code": status_code, "url": url, **_ctx_fetch_diag(ctx)}
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
            **_ctx_fetch_diag(ctx),
        }

    found = len(listings or [])

    inserted_ids = ingest_listings(db, listings)
    inserted = len(inserted_ids or [])

    matched = 0
    queued = 0

    if wishlist is not None:
        candidates = _resolve_candidate_listings(db, source=ctx.source, scraped=listings, inserted_ids=list(inserted_ids or []))
        matches_by_wishlist = match_listings_for_wishlists([wishlist], candidates)
        matched_listings = matches_by_wishlist.get(wishlist.id) or []
        matched = len(matched_listings)
        if matched:
            queued = int(queue_notifications_for_matches(db, wishlist, matched_listings) or 0)

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

    return {"ok": True, "found": found, "inserted": inserted, "matched": matched, "queued": queued, **_ctx_fetch_diag(ctx)}


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
        return {"ok": False, "reason": "blocked", "status_code": status_code, "url": url, **_ctx_fetch_diag(ctx)}
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
            **_ctx_fetch_diag(ctx),
        }

    found = len(listings or [])

    inserted_ids = ingest_listings(db, listings)
    inserted = len(inserted_ids or [])

    total_matched = 0
    total_queued = 0

    # Notify based on the scraped result-set, even if listings already existed in DB.
    # This avoids the common "found but didn't notify" issue when a wishlist is created
    # after a listing was first ingested.
    if wishlists and listings:
        candidates = _resolve_candidate_listings(db, source=ctx.source, scraped=listings, inserted_ids=list(inserted_ids or []))
        if candidates:
            matches_by_wishlist = match_listings_for_wishlists(wishlists, candidates)
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

    return {"ok": True, "found": found, "inserted": inserted, "matched": total_matched, "queued": total_queued, "wishlists": len(wishlists or []), **_ctx_fetch_diag(ctx)}
