from sqlalchemy.orm import Session

from app.scrapers.base import FetchBlocked

from app.services.system_logs_service import log
from app.services.notifications_service import create_queued
from app.services.notifications_queue_service import queue_notifications_for_matches
from app.services.matching_service import match_listings_for_wishlist, match_listings_for_wishlists
from app.services.listings_service import ingest_listings

from app.models.wishlist import Wishlist
from app.models.car_listing import CarListing
from app.models.notification import Notification


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
        log(db, "warn", job_name, "source_blocked", {"status_code": status_code, "url": url})
        return {"ok": False, "reason": "blocked", "status_code": status_code, "url": url}
    except Exception as e:
        err = str(e)
        log(db, "error", job_name, "scrape_failed", {"error": err, "url": search_url})
        return {"ok": False, "reason": "error", "error": err, "url": search_url}

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

    log(db, "info", job_name, "pipeline_summary", {
        "wishlist_id": str(getattr(wishlist, "id", "")) if wishlist else None,
        "url": search_url,
        "found": found,
        "inserted": inserted,
        "matched": matched,
        "queued": queued,
    })

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
        log(db, "warn", job_name, "source_blocked", {"status_code": status_code, "url": url})
        return {"ok": False, "reason": "blocked", "status_code": status_code, "url": url}
    except Exception as e:
        err = str(e)
        log(db, "error", job_name, "scrape_failed", {"error": err, "url": search_url})
        return {"ok": False, "reason": "error", "error": err, "url": search_url}

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

    log(db, "info", job_name, "pipeline_summary_many", {
        "url": search_url,
        "wishlists": len(wishlists or []),
        "found": found,
        "inserted": inserted,
        "matched": total_matched,
        "queued": total_queued,
    })

    db.commit()

    return {"ok": True, "found": found, "inserted": inserted, "matched": total_matched, "queued": total_queued, "wishlists": len(wishlists or [])}
