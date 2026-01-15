from datetime import datetime, timezone
from sqlalchemy.orm import Session

from app.scrapers.base import FetchBlocked

from app.services.system_logs_service import log
from app.services.notifications_service import create_queued, mark_failed_reason
from app.services.notifications_queue_service import queue_notifications_for_matches
from app.services.limits_service import can_send_more_today
from app.services.matching_service import match_listings_for_wishlist
from app.services.listings_service import ingest_listings

from app.models.wishlist import Wishlist
from app.models.car_listing import CarListing
from app.models.notification import Notification


def queue_notifications_for_new_listings(db: Session, component: str, new_listing_ids: list):
    # Carrega anúncios novos
    listings = db.query(CarListing).filter(CarListing.id.in_(new_listing_ids)).all()
    if not listings:
        return

    # Carrega wishlists ativas com filtros
    wishlists = db.query(Wishlist).filter(Wishlist.is_active == True).all()

    queued = 0
    for w in wishlists:
        filters = list(getattr(w, "filters", []) or [])
        for listing in listings:
            # Evita duplicar notification do mesmo anúncio pra mesma wishlist
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


def send_queued_notifications(db: Session, component: str, sender_fn):
    queued = (
        db.query(Notification)
        .filter(Notification.status == "queued")
        .order_by(Notification.created_at.asc())
        .limit(50)
        .all()
    )

    sent = 0
    blocked = 0
    failed = 0

    for n in queued:
        # Limite diário: não acumula
        if not can_send_more_today(db, n.user_id):
            mark_failed_reason(db, n.id, "daily_limit_reached")
            blocked += 1
            continue

        user = n.user
        listing = n.car_listing

        try:
            sender_fn(n, listing, user)
            n.status = "sent"
            n.sent_at = datetime.now(timezone.utc)
            n.error_message = None
            db.commit()
            sent += 1
        except Exception as e:
            n.status = "failed"
            n.error_message = str(e)[:5000]
            db.commit()
            failed += 1

    log(db, "info", component, "send queued notifications result", {
        "sent": sent,
        "blocked_daily_limit": blocked,
        "failed": failed,
        "checked": len(queued),
    })

    log(db, "info", component, "send queued notifications result", {"sent": sent, "blocked": blocked, "failed": failed, "checked": len(queued)})

def scrape_ingest_match(db, job_name, scraper_fn, search_url, wishlist=None) -> dict:
    # 1) scrape
    try:
        listings = scraper_fn(search_url)
    except FetchBlocked as e:
        log(db, "warning", job_name, "source_blocked", {"status_code": e.status_code, "url": e.url})
        return {"ok": False, "reason": "blocked", "status_code": e.status_code, "url": e.url}
    except Exception as e:
        log(db, "error", job_name, "scrape_failed", {"error": str(e), "url": search_url})
        return {"ok": False, "reason": "error", "url": search_url}

    found = len(listings or [])
    if found == 0:
        log(db, "info", job_name, "no_results_found", {"url": search_url})
        return {"ok": True, "reason": "no_results", "found": 0, "inserted": 0, "matched": 0, "queued": 0}

    # 2) ingest (dedupe no DB)
    inserted_ids = ingest_listings(db, listings)  # deve retornar ids inseridos
    inserted = len(inserted_ids or [])

    if inserted == 0:
        log(db, "info", job_name, "no_new_listings_inserted", {"found": found, "url": search_url})
        return {"ok": True, "reason": "no_new", "found": found, "inserted": 0, "matched": 0, "queued": 0}

    # 3) matching (somente novos)
    matched_listings = []
    if wishlist is not None:
        matched_listings = match_listings_for_wishlist(db, wishlist, inserted_ids)

    matched = len(matched_listings)

    # 4) queue notifications
    matched_listings = []
    matched = 0
    queued = 0

    if wishlist is not None and inserted_ids:
        matched_listings = match_listings_for_wishlist(db, wishlist, inserted_ids)
        matched = len(matched_listings)

        if matched:
            queued = queue_notifications_for_matches(db, wishlist, matched_listings)

    db.commit()

    log(db, "info", job_name, "pipeline_summary", {
        "url": search_url,
        "found": found,
        "inserted": inserted,
        "matched": matched,
        "queued": queued,
    })

    return {"ok": True, "reason": None, "found": found, "inserted": inserted, "matched": matched, "queued": queued}