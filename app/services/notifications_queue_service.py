from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy.exc import IntegrityError
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.settings import settings
from app.models.notification import Notification
from app.models.wishlist import Wishlist
from app.scoring.score_v2 import score_ad
from app.services.fipe_service import current_reference_month, listing_vehicle_keys
from app.services.market_stats_service import batch_get_market_stats, cohort_key_for_listing
from app.models.fipe_price import FipePrice
from app.services.cross_source_dedupe_service import evaluate_cross_source_notification_dedupe
from app.services.system_logs_service import log


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
    dedupe_enabled = bool(getattr(settings, "cross_source_dedupe_enabled", False))
    dedupe_shadow_mode = bool(getattr(settings, "cross_source_dedupe_shadow_mode", True))
    dedupe_window_days = int(getattr(settings, "cross_source_dedupe_window_days", 30) or 30)
    ref_month = current_reference_month()
    fipe_rows = {}
    try:
        keys = []
        for l in matched_listings:
            keys.extend(listing_vehicle_keys(l))
        if keys:
            with db.begin_nested():
                rows = db.query(FipePrice).filter(FipePrice.reference_month == ref_month).filter(FipePrice.vehicle_key.in_(list(dict.fromkeys(keys)))).all()
                fipe_rows = {str(r.vehicle_key): r.fipe_price for r in (rows or [])}
    except SQLAlchemyError:
        fipe_rows = {}
    except Exception:
        fipe_rows = {}

    for listing in matched_listings:
        if listing.id in existing_ids:
            continue
        dedupe_eval = None
        if dedupe_enabled:
            try:
                with db.begin_nested():
                    dedupe_eval = evaluate_cross_source_notification_dedupe(
                        db,
                        user_id=wishlist.user_id,
                        wishlist_id=wishlist.id,
                        listing=listing,
                        window_days=dedupe_window_days,
                    )
            except Exception as exc:
                try:
                    log(
                        db,
                        "warning",
                        "notifications_queue",
                        "cross-source dedupe evaluation error",
                        payload={
                            "user_id": str(wishlist.user_id),
                            "wishlist_id": str(wishlist.id),
                            "current_listing_id": str(listing.id),
                            "current_source": getattr(listing, "source", None),
                            "mode": "shadow" if dedupe_shadow_mode else "live",
                            "error": str(exc),
                        },
                    )
                except Exception:
                    pass
                dedupe_eval = None

        if dedupe_enabled and dedupe_eval and dedupe_eval.get("should_suppress"):
            payload = {
                "user_id": str(wishlist.user_id),
                "wishlist_id": str(wishlist.id),
                "current_listing_id": str(listing.id),
                "matched_listing_id": dedupe_eval.get("matched_listing_id"),
                "current_source": dedupe_eval.get("current_source"),
                "matched_source": dedupe_eval.get("matched_source"),
                "fingerprint": dedupe_eval.get("fingerprint"),
                "mode": "shadow" if dedupe_shadow_mode else "live",
            }
            if dedupe_shadow_mode:
                log(db, "info", "notifications_queue", "cross-source dedupe shadow hit", payload={**payload, "would_suppress": True})
            else:
                log(db, "info", "notifications_queue", "cross-source dedupe suppressed", payload={**payload, "suppressed": True})
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
            lkeys = listing_vehicle_keys(listing)
            fipe = next((fipe_rows.get(k) for k in lkeys if k in fipe_rows), None)
            rarity_ratio = None
            rarity_sample = int(ms.sample_size or 0) if ms else None
            if rarity_sample and rarity_sample > 0:
                rarity_ratio = 1.0 / float(rarity_sample)
            sres = score_ad(listing, wishlist, ms, fipe_price=fipe, rarity_ratio=rarity_ratio, rarity_sample_size=rarity_sample)
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


def _to_float(value):
    if value is None:
        return None
    try:
        if isinstance(value, Decimal):
            return float(value)
        return float(value)
    except Exception:
        return None


def _iso_datetime(value):
    if value is None:
        return None
    if not isinstance(value, datetime):
        return None
    dt = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def queue_tracked_price_drop_alert(db: Session, *, tracked) -> bool:
    listing_id = getattr(tracked, "car_listing_id", None)
    wishlist_id = getattr(tracked, "wishlist_id", None)
    if not listing_id or not wishlist_id:
        return False
    current_price = getattr(tracked, "last_observed_price", None)
    current_price_f = _to_float(current_price)
    existing = (
        db.query(Notification.id)
        .filter(Notification.wishlist_id == wishlist_id)
        .filter(Notification.car_listing_id == listing_id)
        .filter(Notification.reason == "tracked_price_drop")
        .filter(Notification.score_v2 == int(current_price) if current_price is not None else Notification.score_v2.is_(None))
        .filter(Notification.status.in_(["queued", "processing", "sent"]))
        .first()
    )
    if existing:
        return False
    wishlist = db.query(Wishlist).filter(Wishlist.id == wishlist_id).first()
    if not wishlist:
        return False
    drop_amount = None
    raw_amount = getattr(tracked, "last_price_change_amount", None)
    raw_amount_f = _to_float(raw_amount)
    if raw_amount_f is not None:
        drop_amount = abs(int(raw_amount_f))
    drop_pct = None
    raw_pct = getattr(tracked, "last_price_change_pct", None)
    raw_pct_f = _to_float(raw_pct)
    if raw_pct_f is not None:
        drop_pct = round(abs(raw_pct_f) * 100, 2)

    initial_price = _to_float(getattr(tracked, "initial_price", None))
    tracked_since = _iso_datetime(getattr(tracked, "created_at", None))
    last_price_change_at = _iso_datetime(getattr(tracked, "last_price_change_at", None))
    last_seen_at = _iso_datetime(getattr(tracked, "last_seen_at", None))
    last_price_drop_alert_price = _to_float(getattr(tracked, "last_price_drop_alert_price", None))

    total_drop_amount = None
    total_drop_pct = None
    if initial_price is not None and current_price_f is not None:
        computed_drop = int(round(initial_price - current_price_f))
        if computed_drop > 0:
            total_drop_amount = computed_drop
            if initial_price > 0:
                total_drop_pct = round((computed_drop / initial_price) * 100, 2)
    db.add(
        Notification(
            user_id=wishlist.user_id,
            wishlist_id=wishlist_id,
            car_listing_id=listing_id,
            status="queued",
            reason="tracked_price_drop",
            # Keep deterministic payload in an existing JSON column (no migration).
            score_breakdown={
                "type": "tracked_price_drop",
                "slot": getattr(tracked, "slot", None),
                "previous_price": int(round(current_price_f - raw_amount_f)) if (current_price_f is not None and raw_amount_f is not None) else None,
                "current_price": int(round(current_price_f)) if current_price_f is not None else None,
                "drop_amount": drop_amount,
                "drop_pct": drop_pct,
                "tracked_listing_id": str(getattr(tracked, "id", "")) or None,
                "wishlist_query": getattr(wishlist, "query", None),
                "initial_price": int(round(initial_price)) if initial_price is not None else None,
                "tracked_since": tracked_since,
                "last_price_change_at": last_price_change_at,
                "last_seen_at": last_seen_at,
                "last_price_drop_alert_price": int(round(last_price_drop_alert_price)) if last_price_drop_alert_price is not None else None,
                "total_drop_amount": total_drop_amount,
                "total_drop_pct": total_drop_pct,
            },
            # Reuse score_v2 for exact-price dedupe (no schema change).
            score_v2=int(round(current_price_f)) if current_price_f is not None else None,
            next_attempt_at=datetime.now(timezone.utc),
            max_attempts=int(getattr(settings, "notification_max_attempts", 3) or 3),
        )
    )
    db.flush()
    return True
