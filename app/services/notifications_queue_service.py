from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.notification import Notification


def queue_notifications_for_matches(
    db: Session,
    wishlist,
    matched_listings: list,
) -> int:
    """
    Enfileira notifications para os anúncios que passaram no matching.

    Regras MVP:
    - status inicial: 'queued'
    - dedupe por (wishlist_id, car_listing_id)
    - NÃO aplica limite diário aqui (isso é no sender)
    """
    if not matched_listings:
        return 0

    queued = 0

    for listing in matched_listings:
        exists = (
            db.query(Notification.id)
            .filter(Notification.wishlist_id == wishlist.id)
            .filter(Notification.car_listing_id == listing.id)
            .first()
        )
        if exists:
            continue

        n = Notification(
            user_id=wishlist.user_id,
            wishlist_id=wishlist.id,
            car_listing_id=listing.id,
            status="queued",
            error_message=None,
        )
        db.add(n)
        queued += 1

    # não commit aqui (o job/service que chama decide)
    return queued
