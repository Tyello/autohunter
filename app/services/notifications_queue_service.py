from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.settings import settings
from app.models.notification import Notification
from app.scoring.score_v2 import score_ad
from app.services.market_stats_service import batch_get_market_stats, cohort_key_for_listing


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

    # Score v2: batch fetch cohort market stats (cheap)
    stats_map = {}
    try:
        stats_map = batch_get_market_stats(db, [l for l in matched_listings if getattr(l, "id", None) and l.id not in existing_ids])
    except Exception:
        # Never let stats retrieval break queuing (table may not exist yet in some envs).
        stats_map = {}

    queued = 0
    for listing in matched_listings:
        if listing.id in existing_ids:
            continue

        ms = None
        try:
            k = cohort_key_for_listing(listing)
            if k:
                ms = stats_map.get(k)
        except Exception:
            ms = None

        # Compute score breakdown (wishlist-specific)
        try:
            sres = score_ad(listing, wishlist, ms)
        except Exception:
            # Never block queueing due to scoring errors; fall back to minimal breakdown
            sres = None

        try:
            with db.begin_nested():
                db.add(
                    Notification(
                        user_id=wishlist.user_id,
                        wishlist_id=wishlist.id,
                        car_listing_id=listing.id,
                        status="queued",
                        error_message=None,
                        score_v2=(sres.total if sres else None),
                        score_breakdown=(sres.to_dict() if sres else None),
                        next_attempt_at=datetime.now(timezone.utc),
                        max_attempts=int(getattr(settings, "notification_max_attempts", 3) or 3),
                    )
                )
                db.flush()
            queued += 1
        except IntegrityError:
            pass

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

    Retorna (contadores):
      - matched: total de listings recebidos (inclui inválidos)
      - queued: quantas notifications foram criadas
      - already_notified: quantas combinações (wishlist_id, car_listing_id) já existiam
      - cap_skipped: quantos matches seriam novos, mas não entraram por limite (max_queue)
      - invalid_listing: quantos listings vieram sem `id`
      - buckets: dict com motivos (para exibir em /admin)
    """
    if not matched_listings:
        return {
            "matched": 0,
            "queued": 0,
            "already_notified": 0,
            "cap_skipped": 0,
            "invalid_listing": 0,
            "buckets": {"queued": 0, "already_notified": 0, "cap_skipped": 0, "invalid_listing": 0},
        }

    matched_total = len(matched_listings)
    invalid_listing = 0
    valid = []
    listing_ids = []
    for l in matched_listings:
        lid = getattr(l, "id", None)
        if not lid:
            invalid_listing += 1
            continue
        valid.append(l)
        listing_ids.append(lid)

    if not listing_ids:
        return {
            "matched": matched_total,
            "queued": 0,
            "already_notified": 0,
            "cap_skipped": 0,
            "invalid_listing": invalid_listing,
            "buckets": {"queued": 0, "already_notified": 0, "cap_skipped": 0, "invalid_listing": invalid_listing},
        }

    existing = (
        db.query(Notification.car_listing_id)
        .filter(Notification.wishlist_id == wishlist.id)
        .filter(Notification.car_listing_id.in_(listing_ids))
        .all()
    )
    existing_ids = {row[0] for row in (existing or [])}

    # candidatos realmente novos (dedupe por existing notification)
    new_listings = [l for l in valid if l.id not in existing_ids]

    cap = int(max_queue) if max_queue is not None else None
    if cap is not None and cap < 0:
        cap = 0

    to_queue = new_listings if cap is None else new_listings[:cap]

    queued = 0
    for listing in to_queue:
        try:
            with db.begin_nested():
                db.add(
                    Notification(
                        user_id=wishlist.user_id,
                        wishlist_id=wishlist.id,
                        car_listing_id=listing.id,
                        status="queued",
                        error_message=None,
                        next_attempt_at=datetime.now(timezone.utc),
                        max_attempts=int(getattr(settings, "notification_max_attempts", 3) or 3),
                    )
                )
                db.flush()
            queued += 1
        except IntegrityError:
            pass

    already_notified = len(valid) - len(new_listings)
    cap_skipped = 0
    if cap is not None:
        cap_skipped = max(0, len(new_listings) - len(to_queue))

    buckets = {
        "queued": queued,
        "already_notified": already_notified,
        "cap_skipped": cap_skipped,
        "invalid_listing": invalid_listing,
    }

    return {
        "matched": matched_total,
        "queued": queued,
        "already_notified": already_notified,
        "cap_skipped": cap_skipped,
        "invalid_listing": invalid_listing,
        "buckets": buckets,
    }
