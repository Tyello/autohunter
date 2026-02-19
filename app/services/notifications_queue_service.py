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

    Regras:
    - status inicial: 'queued'
    - dedupe por (wishlist_id, car_listing_id)
    - **re-tentativa**: se já existir notification com status 'failed',
      re-enfileira (status='queued') limpando reason/error.
    - **re-tentativa** (limite diário): se já existir 'suppressed' com
      reason='daily_limit_reached', re-enfileira (status='queued') quando
      o anúncio aparecer de novo (normalmente no dia seguinte).
    - NÃO aplica limite diário aqui (isso é no sender)
    """
    if not matched_listings:
        return 0

    listing_ids = [getattr(l, "id", None) for l in matched_listings]
    listing_ids = [i for i in listing_ids if i]
    if not listing_ids:
        return 0

    # 1 query por wishlist (ao invés de 1 query por anúncio)
    existing_rows = (
        db.query(Notification)
        .filter(Notification.wishlist_id == wishlist.id)
        .filter(Notification.car_listing_id.in_(listing_ids))
        .all()
    )
    existing_by_listing = {row.car_listing_id: row for row in (existing_rows or [])}

    queued = 0
    for listing in matched_listings:
        existing = existing_by_listing.get(listing.id)

        # Dedupe hard: já enviado ou já enfileirado.
        if existing is not None and existing.status in {"sent", "queued"}:
            continue

        # Retry: falhou antes -> volta para fila.
        if existing is not None and existing.status == "failed":
            existing.status = "queued"
            existing.sent_at = None
            existing.reason = None
            existing.error_message = None
            queued += 1
            continue

        # Retry: daily limit -> requeue quando o anúncio reaparece.
        if existing is not None and existing.status == "suppressed" and (existing.reason or "") == "daily_limit_reached":
            existing.status = "queued"
            existing.sent_at = None
            existing.reason = None
            existing.error_message = None
            queued += 1
            continue

        # Default: cria nova notification.
        if existing is None:
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
