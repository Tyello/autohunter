from __future__ import annotations

import uuid
from datetime import datetime, timezone, timedelta
from decimal import Decimal

from sqlalchemy.exc import IntegrityError
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.settings import settings
from app.models.notification import Notification
from app.models.wishlist import Wishlist
from app.models.fipe_lookup_request import FipeLookupRequest
from app.scoring.score_v2 import score_ad
from app.services.fipe_service import current_reference_month, listing_vehicle_keys
from app.services.market_stats_service import batch_get_market_stats, cohort_key_for_listing
from app.models.fipe_price import FipePrice
from app.services.cross_source_dedupe_service import evaluate_cross_source_notification_dedupe
from app.services.system_logs_service import log
from app.services.fipe_catalog_resolver_service import resolve_listing_to_fipe_candidates, _ensure_month
from app.models.fipe_catalog_entry import FipeCatalogEntry
from app.services.matching_service import _extract_year
from app.services.fipe_monthly_sync_service import normalize_fipe_text


def _fallback_fipe_price_via_catalog(db: Session, listing):
    """Fallback FIPE price lookup via catalog when FipePrice row is missing.

    Calls resolve_listing_to_fipe_candidates with the listing and returns the
    price from the best candidate if confidence_score >= fipe_lookup_min_confidence.

    Returns:
        Decimal or None: The FIPE price if found and confident, None otherwise.
        Never raises exceptions.
    """
    try:
        result = resolve_listing_to_fipe_candidates(
            db,
            listing=listing,
            reference_month=_ensure_month(db, None),
            limit=5
        )

        if result.get("status") == "insufficient_data":
            return None

        best_candidate = result.get("best_candidate")
        if best_candidate is None:
            return None

        confidence = best_candidate.get("confidence_score")
        if confidence is None or confidence < settings.fipe_lookup_min_confidence:
            return None

        catalog_entry_id = best_candidate.get("catalog_entry_id")
        if catalog_entry_id is None:
            return None

        entry = db.query(FipeCatalogEntry).filter(FipeCatalogEntry.id == catalog_entry_id).first()
        if entry is None:
            return None

        return entry.price
    except Exception:
        return None


def _enqueue_reactive_fipe_lookup(db: Session, wishlist, listing) -> None:
    """Enqueue a reactive FIPE lookup when catalog fallback returns None.

    Best-effort, never raises exceptions. Creates a FipeLookupRequest with
    listing_make, listing_model, and target_year for later async processing.

    Implements deduplication and cooldown logic:
    - Skips if make or model are empty after normalization.
    - Skips if year cannot be extracted.
    - Skips if a pending/processing request exists for the same (wishlist, make, model, year).
    - Skips if a recent (done/skipped/failed) request exists within cooldown window.
    - Otherwise creates a new FipeLookupRequest with status='pending'.
    """
    try:
        # Normalize make and model
        make = normalize_fipe_text(getattr(listing, "make", None) or "")
        model = normalize_fipe_text(getattr(listing, "model", None) or "")

        # Skip if make or model is empty after normalization
        if not make or not model:
            return

        # Extract year
        year = _extract_year(listing)
        if year is None:
            return

        # Check cooldown/dedup
        cooldown_cutoff = datetime.now(timezone.utc) - timedelta(days=settings.fipe_lookup_reactive_cooldown_days)

        # Query for existing requests
        existing = db.query(FipeLookupRequest).filter(
            FipeLookupRequest.wishlist_id == wishlist.id,
            FipeLookupRequest.listing_make == make,
            FipeLookupRequest.listing_model == model,
            FipeLookupRequest.target_year == year,
        ).first()

        if existing is not None:
            # Check if it's pending/processing or within cooldown
            if existing.status in ("pending", "processing"):
                return
            # Check if it's within cooldown (status in done/skipped/failed AND processed_at > cutoff)
            if existing.status in ("done", "skipped", "failed"):
                if existing.processed_at is not None:
                    # Ensure both datetimes have timezone for comparison
                    processed_at = existing.processed_at
                    if processed_at.tzinfo is None:
                        processed_at = processed_at.replace(tzinfo=timezone.utc)
                    if processed_at > cooldown_cutoff:
                        return

        # Create new FipeLookupRequest
        db.add(
            FipeLookupRequest(
                id=uuid.uuid4(),
                wishlist_id=wishlist.id,
                listing_make=make,
                listing_model=model,
                target_year=year,
                status="pending",
            )
        )
        db.flush()
    except Exception:
        # Never raise; this is best-effort
        pass


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
            if fipe is None:
                fipe = _fallback_fipe_price_via_catalog(db, listing)
                # Enqueue reactive FIPE lookup if catalog fallback returned None
                if fipe is None:
                    _enqueue_reactive_fipe_lookup(db, wishlist, listing)
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

    # Score v2: batch fetch cohort market stats (cheap)
    stats_map = {}
    try:
        stats_map = batch_get_market_stats(db, to_queue)
    except Exception:
        # Never let stats retrieval break queuing (table may not exist yet in some envs).
        stats_map = {}

    ref_month = current_reference_month()
    fipe_rows = {}
    try:
        keys = []
        for l in to_queue:
            keys.extend(listing_vehicle_keys(l))
        if keys:
            with db.begin_nested():
                rows = db.query(FipePrice).filter(FipePrice.reference_month == ref_month).filter(FipePrice.vehicle_key.in_(list(dict.fromkeys(keys)))).all()
                fipe_rows = {str(r.vehicle_key): r.fipe_price for r in (rows or [])}
    except SQLAlchemyError:
        fipe_rows = {}
    except Exception:
        fipe_rows = {}

    queued = 0
    for listing in to_queue:
        ms = None
        try:
            k = cohort_key_for_listing(listing)
            if k:
                ms = stats_map.get(k)
        except Exception:
            ms = None

        # Compute score breakdown (wishlist-specific), incl. FIPE fallback + reactive enqueue
        try:
            lkeys = listing_vehicle_keys(listing)
            fipe = next((fipe_rows.get(k) for k in lkeys if k in fipe_rows), None)
            if fipe is None:
                fipe = _fallback_fipe_price_via_catalog(db, listing)
                # Enqueue reactive FIPE lookup if catalog fallback returned None
                if fipe is None:
                    _enqueue_reactive_fipe_lookup(db, wishlist, listing)
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
