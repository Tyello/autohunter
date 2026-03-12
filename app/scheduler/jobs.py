from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.scrapers.base import FetchBlocked
from app.scrapers.parse_failure import decide_parse_failure

import traceback

from app.services.admin_programming_alerts import maybe_alert_programming_error

from app.services.system_logs_service import log
from app.services.telemetry_events_service import emit_event
from app.services.notifications_queue_service import (
    queue_notifications_for_matches,
    queue_notifications_for_matches_diag,
)
from app.services.listing_activity_service import build_seen_identity
from app.services.matching_service import match_listings_for_wishlist, match_listings_for_wishlists, match_listings_for_active_wishlists
from app.services.listings_service import ingest_listings, ingest_listings_stats
from app.services.source_url_cursors_service import get_cursor, touch_cursor

from app.models.wishlist import Wishlist
from app.models.car_listing import CarListing
from app.models.notification import Notification
from app.health.collector import HealthCollector
from app.services.source_audit_capture_service import source_audit_capture_service
from app.core.settings import settings


def _is_bug_type(exc_type: str) -> bool:
    return exc_type in {
        "AttributeError",
        "ImportError",
        "ModuleNotFoundError",
        "SyntaxError",
        "NameError",
        "TypeError",
        "PlaywrightInitError",
    }


# ---- Matching/Queue strategy -------------------------------------------------
#
# Historically we only notified on *newly inserted* listings (inserted_ids).
# That creates a blind spot: if a source initially ingests listings with a
# degraded title (e.g. UI/noise), once the scraper is fixed the listing is not
# "new" anymore, so it would never notify.
#
# New behavior: match against the *current scrape result-set* (resolved in DB)
# and enqueue notifications only when no Notification exists yet.
#
# This does NOT "re-alert" because queue_notifications_for_matches dedupes by
# (wishlist_id, car_listing_id) regardless of status.
#
# Safety caps avoid huge backfills on first run.

MAX_CANDIDATE_LISTINGS_PER_RUN = int(settings.match_candidates_per_run)
MAX_QUEUE_PER_WISHLIST_PER_RUN = int(settings.match_max_queue_per_wishlist)


def _parse_incremental_max_new(ctx) -> int | None:
    inc_max_new = (getattr(ctx, "extra", None) or {}).get("incremental_max_new")
    try:
        out = int(inc_max_new) if inc_max_new is not None else None
        return out if out and out > 0 else None
    except Exception:
        return None


def _cut_listings_before_cursor(listings_all: list[dict], cursor_external_id: str | None) -> list[dict]:
    if not cursor_external_id:
        return list(listings_all or [])
    cut: list[dict] = []
    for it in listings_all or []:
        if (it or {}).get("external_id") == cursor_external_id:
            break
        cut.append(it)
    return cut


def _incremental_mode_label(*, inc_mode: str | None, inc_enabled: bool) -> str:
    return inc_mode or ("on" if inc_enabled else "off")


def _capture_if_needed(*, ctx, found: int | None, listings: list[dict], reason: str, stage: str, parse_error: bool = False) -> list[str]:
    sample = (listings or [{}])[0] if listings else {}
    qflags = []
    extras = sample.get("extras") if isinstance(sample, dict) else None
    if isinstance(extras, dict) and isinstance(extras.get("quality_flags"), list):
        qflags = [str(x) for x in extras.get("quality_flags", [])]
    missing = []
    if isinstance(sample, dict):
        if not sample.get("price"):
            missing.append("price")
        if not sample.get("title"):
            missing.append("title")
        if not sample.get("url"):
            missing.append("url")
        if not sample.get("external_id"):
            missing.append("external_id")
    normalized_reason = None if reason in {"post_scrape_check", "post_ingest_check"} else reason
    decision = source_audit_capture_service.decide(
        explicit_reason=normalized_reason,
        found=found,
        missing_critical=missing,
        quality_flags=qflags,
        parse_error=parse_error,
        debug=bool(settings.source_audit_debug),
    )
    if not decision.should_capture:
        return []
    return [str(x) for x in source_audit_capture_service.capture_from_runtime_samples(
        ctx=ctx,
        source=getattr(ctx, "source", "unknown"),
        reasons=list(decision.reasons),
        pipeline_stage=stage,
        external_id=sample.get("external_id") if isinstance(sample, dict) else None,
        extracted_snapshot={
            "price": sample.get("price") if isinstance(sample, dict) else None,
            "title": sample.get("title") if isinstance(sample, dict) else None,
            "url": sample.get("url") if isinstance(sample, dict) else None,
            "external_id": sample.get("external_id") if isinstance(sample, dict) else None,
            "location": sample.get("location") if isinstance(sample, dict) else None,
            "city": sample.get("city") if isinstance(sample, dict) else None,
            "state": sample.get("state") if isinstance(sample, dict) else None,
            "year": sample.get("year") if isinstance(sample, dict) else None,
            "mileage_km": sample.get("mileage_km") if isinstance(sample, dict) else None,
            "thumbnail_url": sample.get("thumbnail_url") if isinstance(sample, dict) else None,
        },
    )]


def _candidate_listings_for_run(db: Session, *, source: str, raw_listings: list[dict], limit: int) -> list[CarListing]:
    """Resolve scraper results to DB rows (existing + newly inserted).

    We use (source, external_id) to map scrape results to car_listings.
    """
    ext_ids: list[str] = []
    seen: set[str] = set()
    for it in (raw_listings or []):
        eid = (it or {}).get("external_id")
        if not eid:
            continue
        eid = str(eid)
        if eid in seen:
            continue
        seen.add(eid)
        ext_ids.append(eid)

    if not ext_ids:
        return []

    q = (
        db.query(CarListing)
        .filter(CarListing.source == source)
        .filter(CarListing.external_id.in_(ext_ids))
        .order_by(CarListing.created_at.desc())
        .limit(int(limit or 0) if int(limit or 0) > 0 else 250)
    )
    return q.all()





def _ctx_fetch_diag(ctx) -> dict:
    return {
        "hybrid_browser_used": bool(getattr(ctx, "_hybrid_browser_used", False)),
        "hybrid_blocked": bool(getattr(ctx, "_hybrid_blocked", False)),
        "hybrid_blocked_status": getattr(ctx, "_hybrid_blocked_status", None),
    }

def queue_notifications_for_new_listings(db: Session, component: str, new_listing_ids: list):
    from datetime import datetime, timezone

    from sqlalchemy.exc import IntegrityError

    from app.core.settings import settings

    listing_rows = db.query(CarListing.id).filter(CarListing.id.in_(new_listing_ids)).all()
    listing_ids = [row[0] for row in listing_rows]
    if not listing_ids:
        return

    wishlists = db.query(Wishlist).filter(Wishlist.is_active.is_(True)).all()
    if not wishlists:
        return

    wishlist_ids = [w.id for w in wishlists]
    existing = db.query(Notification.user_id, Notification.wishlist_id, Notification.car_listing_id).filter(
        Notification.wishlist_id.in_(wishlist_ids),
        Notification.car_listing_id.in_(listing_ids),
    ).all()
    existing_keys = {(row[0], row[1], row[2]) for row in existing}

    queued_count = 0
    for w in wishlists:
        for listing_id in listing_ids:
            key = (w.user_id, w.id, listing_id)
            if key in existing_keys:
                continue
            try:
                with db.begin_nested():
                    db.add(Notification(
                        user_id=w.user_id,
                        wishlist_id=w.id,
                        car_listing_id=listing_id,
                        status="queued",
                        next_attempt_at=datetime.now(timezone.utc),
                        max_attempts=int(getattr(settings, "notification_max_attempts", 3) or 3),
                    ))
                    db.flush()
                queued_count += 1
            except IntegrityError:
                continue

    log(db, "info", component, "queued notifications", {
        "queued": queued_count,
        "listings": len(listing_ids),
        "wishlists": len(wishlists),
    })
    db.commit()


def scrape_ingest_match(db, job_name, scraper_fn, search_url, *, ctx, wishlist=None, health: HealthCollector | None = None) -> dict:
    try:
        # Prefer keyword-arg calling. Some scrapers are defined as:
        #   scrape(url, limit=50, ctx=None)
        # and the orchestration layer always passes ctx.
        # Calling positionally would bind ctx into `limit` and crash later.
        try:
            listings = scraper_fn(search_url, ctx=ctx)
        except TypeError:
            # Back-compat for older scrapers that only accept positional ctx.
            listings = scraper_fn(search_url, ctx)
    except FetchBlocked as e:
        status_code = getattr(e, "status_code", None)
        url = getattr(e, "url", search_url)
        emit_event(db, level="warn", event_type="source_blocked", source=ctx.source, message="source_blocked", evidence={"status_code": status_code, "url": url}, tags=["blocked"])
        log(db, "warn", job_name, "source_blocked", {"status_code": status_code, "url": url}, source=ctx.source, event_type="source_blocked", tags=["blocked"])
        return {"ok": False, "reason": "blocked", "status_code": status_code, "url": url, "error": str(e), "audit_artifacts": _capture_if_needed(ctx=ctx, found=None, listings=[], reason="blocked", stage="scrape_exception"), **_ctx_fetch_diag(ctx)}
    except Exception as e:
        exc_type = type(e).__name__
        err = f"{exc_type}: {e}"
        tb = traceback.format_exc(limit=6)
        emit_event(db, level="error", event_type="scrape_failed", source=ctx.source, message="scrape_failed", evidence={"error": err, "url": search_url, "exc_type": exc_type}, tags=["error"])
        log(db, "error", job_name, "scrape_failed", {"error": err, "url": search_url, "tb": tb}, source=ctx.source, event_type="scrape_failed", tags=["error"])
        # alerta só admins (throttled) quando for erro de programação
        try:
            maybe_alert_programming_error(job_name, e, url=search_url)
        except Exception:
            pass
        return {
            "ok": False,
            "reason": "error",
            "error": err,
            "url": search_url,
            "exc_type": exc_type,
            "is_bug": _is_bug_type(exc_type),
            "audit_artifacts": _capture_if_needed(ctx=ctx, found=None, listings=[], reason="parse_or_runtime_error", stage="scrape_exception", parse_error=True),
            **_ctx_fetch_diag(ctx),
        }

    listings_all = list(listings or [])
    found = len(listings_all)
    parse_failure = decide_parse_failure(
        source=str(getattr(ctx, "source", "") or ""),
        url=search_url,
        found=found,
        adapter_meta=getattr(ctx, "_last_adapter_meta", None),
    )
    if parse_failure is not None:
        err = parse_failure.as_error(source=str(getattr(ctx, "source", "") or "unknown"), url=search_url)
        emit_event(db, level="error", event_type="scrape_parse_failure", source=ctx.source, message="scrape_parse_failure", evidence={"error": err, "url": search_url, "classification": parse_failure.classification, "impact": parse_failure.impact}, tags=["error", "parse_failure"])
        log(db, "error", job_name, "scrape_parse_failure", {"error": err, "url": search_url, "classification": parse_failure.classification, "impact": parse_failure.impact}, source=ctx.source, event_type="scrape_parse_failure", tags=["error", "parse_failure"])
        return {
            "ok": False,
            "reason": "error",
            "error": err,
            "url": search_url,
            "exc_type": "ParseFailure",
            "is_bug": False,
            "audit_artifacts": _capture_if_needed(ctx=ctx, found=found, listings=listings_all, reason="explicit_parse_failure", stage="post_scrape", parse_error=True),
            **_ctx_fetch_diag(ctx),
        }
    audit_artifacts = _capture_if_needed(ctx=ctx, found=found, listings=listings_all, reason="post_scrape_check", stage="post_scrape")
    if health is not None:
        health.inc("found", found)

    thumb_present = sum(1 for it in listings_all if (it or {}).get("thumbnail_url"))
    thumb_rate = (thumb_present / found) if found else 0.0

    # Incremental mode (per source+url) - default OFF unless enabled via source_configs.extra
    inc_enabled = bool((getattr(ctx, "extra", None) or {}).get("incremental_enabled", False))
    inc_max_new_i = _parse_incremental_max_new(ctx)

    listings_to_ingest = listings_all
    inc_mode = None
    inc_cursor = None
    if inc_enabled and found:
        try:
            cur = get_cursor(db, source=ctx.source, url=search_url)
            inc_cursor = getattr(cur, "last_external_id", None) if cur else None
            top = (listings_all[0] or {}).get("external_id")
            if cur and top and top == inc_cursor:
                # nothing changed (top listing unchanged) -> skip DB work
                touch_cursor(db, source=ctx.source, url=search_url, last_external_id=top)
                emit_event(db, level="info", event_type="pipeline_summary", source=ctx.source, message="pipeline_summary", evidence={
                    "wishlist_id": str(getattr(wishlist, "id", "")) if wishlist else None,
                    "url": search_url,
                    "found": found,
                    "inserted": 0,
                    "updated": 0,
                    "upserted": 0,
                    "matched": 0,
                    "queued": 0,
                    "thumb_present": thumb_present,
                    "thumb_rate": thumb_rate,
                    "incremental": {"mode": "skip", "cursor": top},
                }, tags=["ok", "incremental"])
                log(db, "info", job_name, "pipeline_summary", {
                    "wishlist_id": str(getattr(wishlist, "id", "")) if wishlist else None,
                    "url": search_url,
                    "found": found,
                    "inserted": 0,
                    "updated": 0,
                    "upserted": 0,
                    "matched": 0,
                    "queued": 0,
                    "thumb_present": thumb_present,
                    "thumb_rate": thumb_rate,
                    "incremental": {"mode": "skip", "cursor": top},
                }, source=ctx.source, event_type="pipeline_summary", tags=["ok", "incremental"])
                db.commit()
                return {"ok": True, "found": found, "inserted": 0, "updated": 0, "upserted": 0, "matched": 0, "queued": 0, "thumb_present": thumb_present, "thumb_rate": thumb_rate, "incremental": "skip", "audit_artifacts": audit_artifacts, **_ctx_fetch_diag(ctx)}

            # ingest only listings before the cursor (still match on full set)
            if cur and inc_cursor:
                inc_mode = "cut"
                listings_to_ingest = _cut_listings_before_cursor(listings_all, inc_cursor)
                if inc_max_new_i is not None:
                    listings_to_ingest = listings_to_ingest[:inc_max_new_i]
        except Exception:
            # never let cursor logic break the pipeline
            listings_to_ingest = listings_all

    ing = ingest_listings_stats(db, listings_to_ingest)
    inserted_new = int(getattr(ing, "inserted_new", 0) or 0)
    if health is not None:
        health.inc("inserted", inserted_new)
    updated = int(getattr(ing, "updated", 0) or 0)
    upserted = int(getattr(ing, "upserted", 0) or 0)

    matched = 0
    queued = 0
    already_notified = 0
    reason_buckets = {"queued": 0, "already_notified": 0, "cap_skipped": 0, "invalid_listing": 0}
    # Match against the current scrape set (existing + new), then queue only if not notified yet.
    if wishlist is not None:
        candidates = _candidate_listings_for_run(
            db,
            source=ctx.source,
            raw_listings=listings_all,
            limit=MAX_CANDIDATE_LISTINGS_PER_RUN,
        )
        if candidates:
            matches_by = match_listings_for_wishlists([wishlist], candidates)
            matched_listings = matches_by.get(wishlist.id) or []
            matched = len(matched_listings)
            if health is not None:
                health.inc("matched", matched)
            if matched:
                diag = queue_notifications_for_matches_diag(
                    db,
                    wishlist,
                    matched_listings[:MAX_QUEUE_PER_WISHLIST_PER_RUN],
                    max_queue=MAX_QUEUE_PER_WISHLIST_PER_RUN,
                )
                queued = int(diag.get("queued") or 0)
                already_notified = int(diag.get("already_notified") or 0)
                if health is not None:
                    health.inc("queued", queued)
                    health.count("queued", queued)
                    health.inc("already_notified", already_notified)
                    health.count("already_notified", already_notified)
                    cap_skipped = int(diag.get("cap_skipped") or 0)
                    invalid_listing = int(diag.get("invalid_listing") or 0)
                    if cap_skipped:
                        health.inc("filtered_out", cap_skipped)
                    if invalid_listing:
                        health.inc("skipped", invalid_listing)
                        health.count("missing_fields_other", invalid_listing)
                for k, v in (diag.get("buckets") or {}).items():
                    reason_buckets[k] = int(reason_buckets.get(k, 0)) + int(v or 0)

    else:
        # Scheduler/source runs (wishlist agnóstica): matching escalável via token index.
        # Avalia apenas candidatos e enfileira por wishlist.
        candidates = _candidate_listings_for_run(
            db,
            source=ctx.source,
            raw_listings=listings_all,
            limit=MAX_CANDIDATE_LISTINGS_PER_RUN,
        )
        if candidates:
            matches_by, mstats = match_listings_for_active_wishlists(db, candidates)
            # flatten + queue per wishlist
            for wid, items in (matches_by or {}).items():
                w = db.query(Wishlist).filter(Wishlist.id == wid).first()
                if not w or not items:
                    continue
                diag = queue_notifications_for_matches_diag(
                    db,
                    w,
                    items[:MAX_QUEUE_PER_WISHLIST_PER_RUN],
                    max_queue=MAX_QUEUE_PER_WISHLIST_PER_RUN,
                )
                matched += int(diag.get("matched") or 0)
                queued += int(diag.get("queued") or 0)
                already_notified += int(diag.get("already_notified") or 0)
                if health is not None:
                    health.inc("matched", int(diag.get("matched") or 0))
                    health.inc("queued", int(diag.get("queued") or 0))
                    health.count("queued", int(diag.get("queued") or 0))
                    health.inc("already_notified", int(diag.get("already_notified") or 0))
                    health.count("already_notified", int(diag.get("already_notified") or 0))
                    cap_skipped = int(diag.get("cap_skipped") or 0)
                    invalid_listing = int(diag.get("invalid_listing") or 0)
                    if cap_skipped:
                        health.inc("filtered_out", cap_skipped)
                    if invalid_listing:
                        health.inc("skipped", invalid_listing)
                        health.count("missing_fields_other", invalid_listing)
                for k, v in (diag.get("buckets") or {}).items():
                    reason_buckets[k] = int(reason_buckets.get(k, 0)) + int(v or 0)
            # expose matching scalability stats for admin/telemetry
            object.__setattr__(ctx, "_matching_stats", mstats)

    # Update cursor on success (top item)
    if inc_enabled and found:
        try:
            top = (listings_all[0] or {}).get("external_id")
            if top:
                touch_cursor(db, source=ctx.source, url=search_url, last_external_id=top)
        except Exception:
            pass

    emit_event(db, level="info", event_type="pipeline_summary", source=ctx.source, message="pipeline_summary", evidence={
        "wishlist_id": str(getattr(wishlist, "id", "")) if wishlist else None,
        "url": search_url,
        "found": found,
        "inserted": inserted_new,
        "updated": updated,
        "upserted": upserted,
        "matched": matched,
        "matching": getattr(ctx, "_matching_stats", None),
        "queued": queued,
        "already_notified": already_notified,
        "reason_buckets": reason_buckets,
        "thumb_present": thumb_present,
        "thumb_rate": thumb_rate,
        "incremental": {"mode": _incremental_mode_label(inc_mode=inc_mode, inc_enabled=inc_enabled), "cursor": inc_cursor},
    }, tags=["ok"])

    log(db, "info", job_name, "pipeline_summary", {
        "wishlist_id": str(getattr(wishlist, "id", "")) if wishlist else None,
        "url": search_url,
        "found": found,
        "inserted": inserted_new,
        "updated": updated,
        "upserted": upserted,
        "matched": matched,
        "matching": getattr(ctx, "_matching_stats", None),
        "queued": queued,
        "already_notified": already_notified,
        "reason_buckets": reason_buckets,
        "thumb_present": thumb_present,
        "thumb_rate": thumb_rate,
        "incremental": {"mode": _incremental_mode_label(inc_mode=inc_mode, inc_enabled=inc_enabled), "cursor": inc_cursor},
    }, source=ctx.source, event_type="pipeline_summary", tags=["ok"])

    db.commit()

    return {"ok": True, "found": found, "inserted": inserted_new, "updated": updated, "upserted": upserted, "matched": matched,
        "matching": getattr(ctx, "_matching_stats", None), "queued": queued, "already_notified": already_notified, "reason_buckets": reason_buckets, "thumb_present": thumb_present, "thumb_rate": thumb_rate, "incremental": _incremental_mode_label(inc_mode=inc_mode, inc_enabled=inc_enabled), **_ctx_fetch_diag(ctx)}


def scrape_ingest_match_many(db, job_name, scraper_fn, search_url, *, ctx, wishlists: list[Wishlist], health: HealthCollector | None = None) -> dict:
    """Scrape once, ingest once, then match+queue for many wishlists.

    This collapses duplicate work when multiple users share the same query/URL for a given source.
    """
    try:
        try:
            listings = scraper_fn(search_url, ctx=ctx)
        except TypeError:
            listings = scraper_fn(search_url, ctx)
    except FetchBlocked as e:
        status_code = getattr(e, "status_code", None)
        url = getattr(e, "url", search_url)
        emit_event(db, level="warn", event_type="source_blocked", source=ctx.source, message="source_blocked", evidence={"status_code": status_code, "url": url}, tags=["blocked"])
        log(db, "warn", job_name, "source_blocked", {"status_code": status_code, "url": url}, source=ctx.source, event_type="source_blocked", tags=["blocked"])
        return {"ok": False, "reason": "blocked", "status_code": status_code, "url": url, "error": str(e), "audit_artifacts": _capture_if_needed(ctx=ctx, found=None, listings=[], reason="blocked", stage="scrape_exception"), **_ctx_fetch_diag(ctx)}
    except Exception as e:
        exc_type = type(e).__name__
        err = f"{exc_type}: {e}"
        tb = traceback.format_exc(limit=6)
        emit_event(db, level="error", event_type="scrape_failed", source=ctx.source, message="scrape_failed", evidence={"error": err, "url": search_url, "exc_type": exc_type}, tags=["error"])
        log(db, "error", job_name, "scrape_failed", {"error": err, "url": search_url, "tb": tb}, source=ctx.source, event_type="scrape_failed", tags=["error"])
        # alerta só admins (throttled) quando for erro de programação
        try:
            maybe_alert_programming_error(job_name, e, url=search_url)
        except Exception:
            pass
        return {
            "ok": False,
            "reason": "error",
            "error": err,
            "url": search_url,
            "exc_type": exc_type,
            "is_bug": _is_bug_type(exc_type),
            "audit_artifacts": _capture_if_needed(ctx=ctx, found=None, listings=[], reason="parse_or_runtime_error", stage="scrape_exception", parse_error=True),
            **_ctx_fetch_diag(ctx),
        }

    listings_all = list(listings or [])
    found = len(listings_all)
    parse_failure = decide_parse_failure(
        source=str(getattr(ctx, "source", "") or ""),
        url=search_url,
        found=found,
        adapter_meta=getattr(ctx, "_last_adapter_meta", None),
    )
    if parse_failure is not None:
        err = parse_failure.as_error(source=str(getattr(ctx, "source", "") or "unknown"), url=search_url)
        emit_event(db, level="error", event_type="scrape_parse_failure", source=ctx.source, message="scrape_parse_failure", evidence={"error": err, "url": search_url, "classification": parse_failure.classification, "impact": parse_failure.impact}, tags=["error", "parse_failure"])
        log(db, "error", job_name, "scrape_parse_failure", {"error": err, "url": search_url, "classification": parse_failure.classification, "impact": parse_failure.impact}, source=ctx.source, event_type="scrape_parse_failure", tags=["error", "parse_failure"])
        return {
            "ok": False,
            "reason": "error",
            "error": err,
            "url": search_url,
            "exc_type": "ParseFailure",
            "is_bug": False,
            "audit_artifacts": _capture_if_needed(ctx=ctx, found=found, listings=listings_all, reason="explicit_parse_failure", stage="post_scrape", parse_error=True),
            **_ctx_fetch_diag(ctx),
        }
    audit_artifacts = _capture_if_needed(ctx=ctx, found=found, listings=listings_all, reason="post_scrape_check", stage="post_scrape")
    if health is not None:
        health.inc("found", found)

    thumb_present = sum(1 for it in listings_all if (it or {}).get("thumbnail_url"))
    thumb_rate = (thumb_present / found) if found else 0.0

    inc_enabled = bool((getattr(ctx, "extra", None) or {}).get("incremental_enabled", False))
    inc_max_new_i = _parse_incremental_max_new(ctx)

    listings_to_ingest = listings_all
    inc_mode = None
    inc_cursor = None
    if inc_enabled and found:
        try:
            cur = get_cursor(db, source=ctx.source, url=search_url)
            inc_cursor = getattr(cur, "last_external_id", None) if cur else None
            top = (listings_all[0] or {}).get("external_id")

            if cur and top and top == inc_cursor:
                touch_cursor(db, source=ctx.source, url=search_url, last_external_id=top)
                emit_event(db, level="info", event_type="pipeline_summary_many", source=ctx.source, message="pipeline_summary_many", evidence={
                    "url": search_url,
                    "wishlists": len(wishlists or []),
                    "found": found,
                    "inserted": 0,
                    "updated": 0,
                    "upserted": 0,
                    "matched": 0,
                    "queued": 0,
                    "thumb_present": thumb_present,
                    "thumb_rate": thumb_rate,
                    "incremental": {"mode": "skip", "cursor": top},
                }, tags=["ok", "incremental"])
                log(db, "info", job_name, "pipeline_summary_many", {
                    "url": search_url,
                    "wishlists": len(wishlists or []),
                    "found": found,
                    "inserted": 0,
                    "updated": 0,
                    "upserted": 0,
                    "matched": 0,
                    "queued": 0,
                    "thumb_present": thumb_present,
                    "thumb_rate": thumb_rate,
                    "incremental": {"mode": "skip", "cursor": top},
                }, source=ctx.source, event_type="pipeline_summary_many", tags=["ok", "incremental"])
                db.commit()
                return {"ok": True, "found": found, "inserted": 0, "matched": 0, "queued": 0, "wishlists": len(wishlists or []), "thumb_present": thumb_present, "thumb_rate": thumb_rate, "incremental": "skip", "audit_artifacts": audit_artifacts, **_ctx_fetch_diag(ctx)}

            if cur and inc_cursor:
                inc_mode = "cut"
                listings_to_ingest = _cut_listings_before_cursor(listings_all, inc_cursor)
                if inc_max_new_i is not None:
                    listings_to_ingest = listings_to_ingest[:inc_max_new_i]
        except Exception:
            listings_to_ingest = listings_all

    ing = ingest_listings_stats(db, listings_to_ingest)
    inserted_new = int(getattr(ing, "inserted_new", 0) or 0)
    if health is not None:
        health.inc("inserted", inserted_new)
    updated = int(getattr(ing, "updated", 0) or 0)
    upserted = int(getattr(ing, "upserted", 0) or 0)

    total_matched = 0
    total_queued = 0
    total_already_notified = 0
    reason_buckets = {"queued": 0, "already_notified": 0, "cap_skipped": 0, "invalid_listing": 0}
    seen_identities_by_wishlist: dict[str, list] = {}

    # Match against the current scrape set (existing + new), then queue only if not notified yet.
    if wishlists:
        candidates = _candidate_listings_for_run(
            db,
            source=ctx.source,
            raw_listings=listings_all,
            limit=MAX_CANDIDATE_LISTINGS_PER_RUN,
        )
        if candidates:
            matches_by_wishlist = match_listings_for_wishlists(wishlists, candidates)

            for w in wishlists:
                matched_listings = matches_by_wishlist.get(w.id) or []
                if matched_listings:
                    wid_key = str(w.id)
                    bucket = seen_identities_by_wishlist.setdefault(wid_key, [])
                    for ml in matched_listings:
                        ident = build_seen_identity(ml)
                        if ident is not None:
                            bucket.append(ident)
                m = len(matched_listings)
                if not m:
                    continue
                total_matched += m
                if health is not None:
                    health.inc("matched", m)
                diag = queue_notifications_for_matches_diag(
                    db,
                    w,
                    matched_listings[:MAX_QUEUE_PER_WISHLIST_PER_RUN],
                    max_queue=MAX_QUEUE_PER_WISHLIST_PER_RUN,
                )
                total_queued += int(diag.get("queued") or 0)
                total_already_notified += int(diag.get("already_notified") or 0)
                if health is not None:
                    health.inc("queued", int(diag.get("queued") or 0))
                    health.count("queued", int(diag.get("queued") or 0))
                    health.inc("already_notified", int(diag.get("already_notified") or 0))
                    health.count("already_notified", int(diag.get("already_notified") or 0))
                    cap_skipped = int(diag.get("cap_skipped") or 0)
                    invalid_listing = int(diag.get("invalid_listing") or 0)
                    if cap_skipped:
                        health.inc("filtered_out", cap_skipped)
                    if invalid_listing:
                        health.inc("skipped", invalid_listing)
                        health.count("missing_fields_other", invalid_listing)
                for k, v in (diag.get("buckets") or {}).items():
                    reason_buckets[k] = int(reason_buckets.get(k, 0)) + int(v or 0)

    if inc_enabled and found:
        try:
            top = (listings_all[0] or {}).get("external_id")
            if top:
                touch_cursor(db, source=ctx.source, url=search_url, last_external_id=top)
        except Exception:
            pass

    emit_event(db, level="info", event_type="pipeline_summary_many", source=ctx.source, message="pipeline_summary_many", evidence={
        "url": search_url,
        "wishlists": len(wishlists or []),
        "found": found,
        "inserted": inserted_new,
        "updated": updated,
        "upserted": upserted,
        "matched": total_matched,
        "queued": total_queued,
        "already_notified": total_already_notified,
        "reason_buckets": reason_buckets,
        "thumb_present": thumb_present,
        "thumb_rate": thumb_rate,
        "incremental": {"mode": _incremental_mode_label(inc_mode=inc_mode, inc_enabled=inc_enabled), "cursor": inc_cursor},
    }, tags=["ok"])

    log(db, "info", job_name, "pipeline_summary_many", {
        "url": search_url,
        "wishlists": len(wishlists or []),
        "found": found,
        "inserted": inserted_new,
        "updated": updated,
        "upserted": upserted,
        "matched": total_matched,
        "queued": total_queued,
        "already_notified": total_already_notified,
        "reason_buckets": reason_buckets,
        "thumb_present": thumb_present,
        "thumb_rate": thumb_rate,
        "incremental": {"mode": _incremental_mode_label(inc_mode=inc_mode, inc_enabled=inc_enabled), "cursor": inc_cursor},
    }, source=ctx.source, event_type="pipeline_summary_many", tags=["ok"])

    db.commit()

    return {"ok": True, "found": found, "inserted": inserted_new, "updated": updated, "upserted": upserted, "matched": total_matched, "queued": total_queued, "already_notified": total_already_notified, "reason_buckets": reason_buckets, "wishlists": len(wishlists or []), "thumb_present": thumb_present, "thumb_rate": thumb_rate, "incremental": _incremental_mode_label(inc_mode=inc_mode, inc_enabled=inc_enabled), "audit_artifacts": audit_artifacts, "seen_identities_by_wishlist": seen_identities_by_wishlist, **_ctx_fetch_diag(ctx)}
