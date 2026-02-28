from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.notification import Notification
from app.core.settings import settings


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

    Retorna (contadores):
      - matched: total de listings recebidos (inclui inválidos)
      - queued: quantas notifications foram criadas
      - already_notified: quantas combinações (wishlist_id, car_listing_id) já existiam
      - cap_skipped: quantos matches seriam novos, mas não entraram por limite (max_queue)
      - invalid_listing: quantos listings vieram sem `id`
      - buckets: dict com motivos (para exibir em /admin)

    Buckets adicionais (quando aplicável):
      - user_unreachable: usuário inativo (não deve receber)
      - wishlist_disabled: wishlist desativada
      - price_missing: regra opcional (NOTIFY_REQUIRE_PRICE)
      - thumb_missing: regra opcional (NOTIFY_REQUIRE_THUMB)
      - filtered_by_rules: total de regras de supressão (soma de price_missing/thumb_missing/...)
    """
    if not matched_listings:
        return {
            "matched": 0,
            "queued": 0,
            "already_notified": 0,
            "cap_skipped": 0,
            "invalid_listing": 0,
            "buckets": {
                "queued": 0,
                "already_notified": 0,
                "cap_skipped": 0,
                "invalid_listing": 0,
                "user_unreachable": 0,
                "wishlist_disabled": 0,
                "price_missing": 0,
                "thumb_missing": 0,
                "filtered_by_rules": 0,
            },
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
            "buckets": {
                "queued": 0,
                "already_notified": 0,
                "cap_skipped": 0,
                "invalid_listing": invalid_listing,
                "user_unreachable": 0,
                "wishlist_disabled": 0,
                "price_missing": 0,
                "thumb_missing": 0,
                "filtered_by_rules": 0,
            },
        }

    existing = (
        db.query(Notification.car_listing_id)
        .filter(Notification.wishlist_id == wishlist.id)
        .filter(Notification.car_listing_id.in_(listing_ids))
        .all()
    )
    existing_ids = {row[0] for row in (existing or [])}

    # wishlist/user gates (cheap and consistent)
    user_unreachable = 0
    wishlist_disabled = 0
    try:
        if getattr(wishlist, "is_active", True) is not True:
            wishlist_disabled = len(valid)
    except Exception:
        wishlist_disabled = 0

    try:
        u = getattr(wishlist, "user", None)
        if u is not None and getattr(u, "is_active", True) is not True:
            user_unreachable = len(valid)
    except Exception:
        user_unreachable = 0

    if wishlist_disabled or user_unreachable:
        # nothing should be queued if wishlist/user is not eligible
        buckets = {
            "queued": 0,
            "already_notified": 0,
            "cap_skipped": 0,
            "invalid_listing": invalid_listing,
            "user_unreachable": user_unreachable,
            "wishlist_disabled": wishlist_disabled,
            "price_missing": 0,
            "thumb_missing": 0,
            "filtered_by_rules": int(bool(user_unreachable or wishlist_disabled)) * len(valid),
        }
        return {
            "matched": matched_total,
            "queued": 0,
            "already_notified": 0,
            "cap_skipped": 0,
            "invalid_listing": invalid_listing,
            "buckets": buckets,
        }

    # candidatos realmente novos (dedupe por existing notification)
    new_listings = [l for l in valid if l.id not in existing_ids]

    # Optional notification rules (feature flags)
    require_price = bool(getattr(settings, "notify_require_price", False))
    require_thumb = bool(getattr(settings, "notify_require_thumb", False))
    price_missing = 0
    thumb_missing = 0
    ruled: list = []
    for l in new_listings:
        if require_price and getattr(l, "price", None) in (None, ""):
            price_missing += 1
            continue
        if require_thumb and not (getattr(l, "thumbnail_url", None) or "").strip():
            thumb_missing += 1
            continue
        ruled.append(l)

    new_listings = ruled

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

    already_notified = len(valid) - len(new_listings)
    cap_skipped = 0
    if cap is not None:
        cap_skipped = max(0, len(new_listings) - len(to_queue))

    filtered_by_rules = int(price_missing) + int(thumb_missing)
    buckets = {
        "queued": queued,
        "already_notified": already_notified,
        "cap_skipped": cap_skipped,
        "invalid_listing": invalid_listing,
        "user_unreachable": 0,
        "wishlist_disabled": 0,
        "price_missing": price_missing,
        "thumb_missing": thumb_missing,
        "filtered_by_rules": filtered_by_rules,
    }

    return {
        "matched": matched_total,
        "queued": queued,
        "already_notified": already_notified,
        "cap_skipped": cap_skipped,
        "invalid_listing": invalid_listing,
        "buckets": buckets,
    }
