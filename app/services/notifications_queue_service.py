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


def queue_notifications_for_matches_diag(
    db: Session,
    wishlist,
    matched_listings: list,
    *,
    max_queue: int | None = None,
) -> dict:
    """Enfileira notifications e retorna diagnósticos.

    Útil para admin/telemetria quando temos match>0 mas queued=0.

    Retorna:
      - queued: quantas notifications foram criadas
      - already_notified: quantas combinações (wishlist_id, car_listing_id) já existiam
      - cap_skipped: quantos matches seriam novos, mas não entraram por limite (max_queue)
      - matched: total de listings avaliados
    """
    if not matched_listings:
        return {"queued": 0, "already_notified": 0, "cap_skipped": 0, "matched": 0}

    listing_ids = [getattr(l, "id", None) for l in matched_listings]
    listing_ids = [i for i in listing_ids if i]
    if not listing_ids:
        return {"queued": 0, "already_notified": 0, "cap_skipped": 0, "matched": 0}

    existing = (
        db.query(Notification.car_listing_id)
        .filter(Notification.wishlist_id == wishlist.id)
        .filter(Notification.car_listing_id.in_(listing_ids))
        .all()
    )
    existing_ids = {row[0] for row in (existing or [])}

    # candidatos realmente novos
    new_listings = [l for l in matched_listings if getattr(l, "id", None) and l.id not in existing_ids]

    cap = int(max_queue) if max_queue is not None else None
    if cap is not None and cap < 0:
        cap = 0

    to_queue = new_listings if cap is None else new_listings[:cap]

    queued = 0
    for listing in to_queue:
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

    already_notified = len([l for l in matched_listings if getattr(l, "id", None) in existing_ids])
    cap_skipped = 0
    if cap is not None:
        cap_skipped = max(0, len(new_listings) - len(to_queue))

    return {
        "queued": queued,
        "already_notified": already_notified,
        "cap_skipped": cap_skipped,
        "matched": len(listing_ids),
    }
