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

    listing_ids = [getattr(l, "id", None) for l in matched_listings]
    listing_ids = [i for i in listing_ids if i]
    if not listing_ids:
        return 0

    # 1 query por wishlist (ao invés de 1 query por anúncio)
    existing = (
        db.query(Notification.car_listing_id)
        .filter(Notification.wishlist_id == wishlist.id)
        .filter(Notification.car_listing_id.in_(listing_ids))
        .all()
    )
    existing_ids = {row[0] for row in (existing or [])}

    queued = 0
    for listing in matched_listings:
        if listing.id in existing_ids:
            continue
        db.add(
            Notification(
                user_id=wishlist.user_id,
                wishlist_id=wishlist.id,
                car_listing_id=listing.id,
                status="queued",
                error_message=None,
            )
        )
        queued += 1

    # não commit aqui (o job/service que chama decide)
    return queued
