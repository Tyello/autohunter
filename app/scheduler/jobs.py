from datetime import datetime, timezone
from sqlalchemy.orm import Session

from app.services.system_logs_service import log
from app.services.notifications_service import create_queued, mark_failed_reason, create_queued_if_absent
from app.services.limits_service import can_send_more_today
from app.services.matching_service import text_match, apply_filters

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
            if not text_match(w.query, listing):
                continue
            if filters and not apply_filters(filters, listing):
                continue

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

def scrape_ingest_match(db: Session, component: str, scraper_fn, search_url: str):
    log(db, "info", component, "job started", {"search_url": search_url})

    listings = scraper_fn(search_url)
    inserted_ids = ingest_listings(db, listings)  # ✅ RETURNING ids

    if not inserted_ids:
        log(db, "info", component, "no new listings inserted")
        return

    new_listings = db.query(CarListing).filter(CarListing.id.in_(inserted_ids)).all()

    wishlists = (
        db.query(Wishlist)
        .filter(Wishlist.is_active == True)
        .all()
    )

    queued = 0
    for w in wishlists:
        filters = list(getattr(w, "filters", []) or [])
        for listing in new_listings:
            if not text_match(w.query, listing):
                continue
            if filters and not apply_filters(filters, listing):
                continue

            created = create_queued_if_absent(db, w.user_id, w.id, listing.id)
            if created:
                queued += 1

    log(db, "info", component, "job finished", {
        "scraped": len(listings),
        "inserted_new": len(inserted_ids),
        "queued": queued,
    })