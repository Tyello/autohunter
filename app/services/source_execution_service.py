from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session
from sqlalchemy import select

from app.core.settings import settings
from app.models.source_config import SourceConfig
from app.models.source_state import SourceState
from app.models.wishlist import Wishlist
from app.scheduler.jobs import scrape_ingest_match_many
from app.services.system_logs_service import log
from app.services.source_backoff_service import is_source_allowed, mark_blocked, mark_error, mark_bug, mark_success, mark_skipped
from app.services.source_configs_service import ensure_source_configs, build_scrape_context
from app.services.source_runs_service import record_run
from app.services.telemetry_events_service import emit_event
from app.services.wishlist_sources_service import get_eligible_wishlists_for_source
from app.services.source_execution_helpers import build_scrape_dispatch, build_run_payload
from app.sources.registry import get_source
from app.sources.flags import read_source_impl_flags
from app.sources.media import derive_thumbnail_url
from app.sources.normalize import (
    normalize_fuel_type,
    normalize_listing_type,
    normalize_seller_type,
    normalize_transmission,
)
from app.scrapers.sources import get_scraper
from app.scrapers.webmotors_ops import extract_webmotors_diag
from app.health.collector import HealthCollector
from app.health.classify import classify_error
from app.health.explain import add_anomaly_notes
from app.health.models import RunStatus
from app.services.listing_activity_service import reconcile_listing_activity_for_source_run


logger = logging.getLogger(__name__)


def _ad_to_listing(ad) -> dict[str, Any]:
    location = ad.extras.get("location") or ", ".join([x for x in [ad.city, ad.uf] if x]) or None
    extras = dict(ad.extras or {})
    extras.setdefault("quality_flags", list(ad.quality_flags or ()))
    extras.setdefault("quality_has_critical", any(f in {"invalid_url", "missing_url", "empty_title", "missing_source"} for f in ad.quality_flags))
    thumbnail_url = derive_thumbnail_url(extras.get("thumbnail_url"), extras.get("image_urls"))
    return {
        "source": ad.source,
        "external_id": ad.external_id,
        "url": ad.url,
        "title": ad.title,
        "price": ad.price,
        "currency": ad.currency,
        "location": location,
        "city": ad.city,
        "state": ad.uf,
        "year": ad.year,
        "mileage_km": ad.km,
        "fuel_type": normalize_fuel_type(extras.get("fuel_type")),
        "transmission": normalize_transmission(extras.get("transmission")),
        "images_count": ad.images_count,
        "make": ad.make,
        "model": ad.model,
        "version": extras.get("version"),
        "seller_type": normalize_seller_type(extras.get("seller_type")),
        "listing_type": normalize_listing_type(extras.get("listing_type")),
        "color": extras.get("color"),
        "thumbnail_url": thumbnail_url,
        "raw_payload": extras.get("raw_payload") or {"external_id": ad.external_id, "url": ad.url},
        "extractor_version": extras.get("extractor_version") or "normalize_ad_v2",
        "extras": extras,
    }


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _ensure_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)

def _get_state(db: Session, source: str) -> Optional[SourceState]:
    return db.execute(select(SourceState).where(SourceState.source == source)).scalar_one_or_none()


def _get_cfg(db: Session, source: str) -> Optional[SourceConfig]:
    return db.execute(select(SourceConfig).where(SourceConfig.source == source)).scalar_one_or_none()


def _wishlist_eligibility_snapshot(db: Session, src: str) -> tuple[list[Wishlist], dict[str, int]]:
    return get_eligible_wishlists_for_source(db, src)


def run_source_for_all_wishlists(
    db: Session,
    source_name: str,
    *,
    kind: str = "scheduler",
    force: bool = False,
    ignore_backoff: bool = False,
    run_reason: str | None = None,
) -> Dict[str, Any]:
    """Execute one source against all active wishlists (grouped by URL).

    This is the single runner used by:
    - scheduler tick jobs
    - admin runall (force=True)

    It is DB-driven: enable/schedule/cooldown/rate-limit/proxy/browser flags come from `source_configs`.
    """
    src = (source_name or "").strip().lower()
    plugin = get_source(src)
    component = f"{kind}_{src}"
    reason = (run_reason or kind or "scheduler").strip().lower()

    if not plugin:
        return {"ok": False, "status": "error", "error": f"unknown_source:{src}"}

    # Ensure DB rows exist (seed defaults once)
    ensure_source_configs(db)

    cfg = _get_cfg(db, src)
    if not cfg:
        return {"ok": False, "status": "error", "error": f"missing_source_config:{src}"}

    # Disabled?
    if not force and not bool(cfg.is_enabled):
        return {"ok": True, "status": "skipped", "reason": "disabled", "run_reason": reason}

    # Not implemented?
    if plugin.scrape is None:
        if not force:
            return {"ok": True, "status": "skipped", "reason": "not_implemented", "run_reason": reason}
        return {"ok": False, "status": "error", "error": "not_implemented"}

    # Playwright checks
    if (plugin.fetch_mode == "browser" or bool(cfg.force_browser)) and not bool(settings.enable_playwright):
        mark_skipped(db, src, "playwright_off")
        run_row = record_run(
            db,
            source=src,
            kind=kind,
            status="skipped",
            payload={"reason": "playwright_off", "run_reason": reason},
            proxy_server=cfg.proxy_server,
            browser_fallback_enabled=bool(cfg.browser_fallback_enabled),
            force_browser=bool(cfg.force_browser),
        )
        emit_event(
            db,
            level="warn",
            event_type="playwright_off",
            source=src,
            run_id=run_row.id,
            message="playwright_off",
                evidence={"reason": "playwright_off", "kind": kind, "run_reason": reason},
            tags=[kind, reason, "ops"],
        )
        log(db, "warn", component, "playwright_off", source=src, run_id=run_row.id, event_type="playwright_off", tags=[kind, reason, "ops"])
        db.commit()
        return {"ok": True, "status": "skipped", "reason": "playwright_off", "run_reason": reason}

    # Backoff checks
    if not (force or ignore_backoff):
        avail = is_source_allowed(db, src)
        if not avail.is_allowed:
            mark_skipped(db, src, "backoff", {"next_allowed_at": str(avail.next_allowed_at) if avail.next_allowed_at else None})
            run_row = record_run(
                db,
                source=src,
                kind=kind,
                status="skipped",
                payload={"reason": "backoff", "next_allowed_at": str(avail.next_allowed_at) if avail.next_allowed_at else None, "run_reason": reason},
                proxy_server=cfg.proxy_server,
                browser_fallback_enabled=bool(cfg.browser_fallback_enabled),
                force_browser=bool(cfg.force_browser),
            )
            emit_event(
                db,
                level="info",
                event_type="skipped_backoff",
                source=src,
                run_id=run_row.id,
                message="skipped_backoff",
                evidence={"next_allowed_at": str(avail.next_allowed_at) if avail.next_allowed_at else None, "kind": kind, "run_reason": reason},
                tags=[kind, reason, "ops"],
            )
            log(db, "info", component, "skipped_backoff", {"next_allowed_at": str(avail.next_allowed_at) if avail.next_allowed_at else None}, source=src, run_id=run_row.id, event_type="skipped_backoff", tags=[kind, reason, "ops"])
            db.commit()
            return {"ok": True, "status": "skipped", "reason": "backoff", "next_allowed_at": avail.next_allowed_at, "run_reason": reason}

    # Schedule / due checks (based on last_effective_run_at)
    if not force:
        minutes = int(cfg.sched_minutes or 0)
        if minutes <= 0:
            return {"ok": True, "status": "skipped", "reason": "sched_0", "run_reason": reason}

        st = _get_state(db, src)
        last_eff = _ensure_utc(st.last_effective_run_at) if st else None
        if last_eff and (_utcnow() - last_eff) < timedelta(minutes=minutes):
            return {"ok": True, "status": "skipped", "reason": "not_due", "run_reason": reason}

    # Feed sources (maintenance/inventory) can run without wishlists.
    if not bool(getattr(plugin, "supports_wishlist_monitoring", True)):
        url = plugin.build_url("")
        groups: dict[str, dict] = {url: {"query": None, "wishlists": []}}
        wishlists = []
    else:
        wishlists, wishlist_stats = _wishlist_eligibility_snapshot(db, src)
        if not wishlists:
            skip_reason = "no_active_wishlists" if int(wishlist_stats.get("active_wishlists") or 0) == 0 else "no_matching_wishlists"
            log(db, "info", component, skip_reason, payload=wishlist_stats)
            db.commit()
            return {
                "ok": True,
                "status": "skipped",
                "reason": skip_reason,
                "run_reason": reason,
                **wishlist_stats,
            }

        groups = {}
        for w in wishlists:
            url = plugin.build_url(w.query)
            g = groups.get(url)
            if g is None:
                groups[url] = {"query": w.query, "wishlists": [w]}
            else:
                g["wishlists"].append(w)

        if not groups:
            log(db, "info", component, "no_matching_wishlists", payload=wishlist_stats)
            db.commit()
            return {"ok": True, "status": "skipped", "reason": "no_matching_wishlists", "run_reason": reason, **wishlist_stats}

    ctx = build_scrape_context(db, src)
    flags = read_source_impl_flags(cfg.extra)
    v2_scraper = get_scraper(src)

    _scrape_dispatch = build_scrape_dispatch(
        src=src,
        flags=flags,
        plugin=plugin,
        v2_scraper=v2_scraper,
        ad_to_listing=_ad_to_listing,
    )

    groups_count = len(groups)
    total_wishlists = sum(len(g.get("wishlists") or []) for g in groups.values())

    t0 = datetime.now(timezone.utc)
    health = HealthCollector(source_name=src)
    total_found = 0
    total_inserted = 0
    total_matched = 0
    total_queued = 0
    total_already_notified = 0
    total_reason_buckets: dict[str, int] = {}
    total_thumb_present = 0
    seen_identities_by_wishlist: dict[str, list] = {}
    any_hybrid_browser = False
    any_hybrid_blocked = False
    last_hybrid_blocked_status: int | None = None

    for url, g in groups.items():
        job_name = f"scraper_{src}"
        res = scrape_ingest_match_many(
            db,
            job_name,
            _scrape_dispatch,
            url,
            ctx=ctx,
            wishlists=g["wishlists"],
            health=health,
        )

        any_hybrid_browser = any_hybrid_browser or bool(res.get("hybrid_browser_used"))
        any_hybrid_blocked = any_hybrid_blocked or bool(res.get("hybrid_blocked"))
        if res.get("hybrid_blocked_status") is not None:
            last_hybrid_blocked_status = int(res.get("hybrid_blocked_status"))

        if not res.get("ok"):
            reason = res.get("reason") or "error"
            wm_diag = extract_webmotors_diag(res.get("error")) if src == "webmotors" else None
            category = "unknown_error"
            retryable = None
            http_status = None
            status_cls = RunStatus.ERR
            bucket = "unknown_error"
            if reason == "blocked":
                status_cls = RunStatus.BLOCKED
                hs = int(res.get("status_code") or 0)
                category = f"http_{hs}" if hs else "blocked"
                http_status = hs or None
                retryable = True
                bucket = "blocked_403" if hs == 403 else "blocked_429" if hs == 429 else "blocked_captcha"
                if isinstance(wm_diag, dict) and wm_diag.get("bucket") == "BLOCKED":
                    category = "webmotors_blocked"
                health.inc("blocked", 1)
            else:
                if isinstance(wm_diag, dict):
                    wmb = str(wm_diag.get("bucket") or "").upper()
                    if wmb == "PROXY":
                        category, status_cls, retryable, bucket = "webmotors_proxy", RunStatus.PROXY, True, "proxy_error"
                    elif wmb == "NET":
                        category, status_cls, retryable, bucket = "webmotors_net", RunStatus.NET, True, "timeout"
                    elif wmb == "BLOCKED":
                        category, status_cls, retryable, bucket = "webmotors_blocked", RunStatus.BLOCKED, True, "blocked_captcha"
                    elif wmb == "PARSER":
                        category, status_cls, retryable, bucket = "webmotors_parser", RunStatus.PARSE, False, "parse_error"
                    elif wmb == "BROWSER":
                        category, status_cls, retryable, bucket = "webmotors_browser", RunStatus.ERR, True, "unknown_error"
                    else:
                        category, status_cls, retryable, bucket = "webmotors_unknown", RunStatus.ERR, True, "unknown_error"
                else:
                    category, status_cls, retryable, http_status, bucket = classify_error(Exception(str(res.get("error") or reason)))
            health.inc("errors", 1)
            health.count(bucket, 1)
            if isinstance(wm_diag, dict):
                health.add_note(
                    "wm_diag "
                    f"bucket={wm_diag.get('bucket')} stage={wm_diag.get('stage')} "
                    f"path={wm_diag.get('fetch_path')} attempts={wm_diag.get('attempt')} "
                    f"http={wm_diag.get('http_status')} cards={wm_diag.get('cards_found')} "
                    f"title={wm_diag.get('page_title')} final_url={wm_diag.get('final_url')}"
                )
            health.set_error(category, str(res.get("error") or reason), http_status=http_status, retryable=retryable)
            run_summary_err = add_anomaly_notes(health.finalize(status_cls)).model_dump(mode="json")
            if reason == "blocked":
                duration_ms = int((datetime.now(timezone.utc) - t0).total_seconds() * 1000)
                minutes = mark_blocked(
                    db,
                    src,
                    base_cooldown_minutes=(max(int(cfg.cooldown_minutes or 0), 15) if (src or '').lower()=='webmotors' else max(int(cfg.cooldown_minutes or 0), 1)),
                    http_status=res.get("status_code"),
                    url=res.get("url") or url,
                )
                payload = build_run_payload(
                    run_summary=run_summary_err,
                    run_reason=reason,
                    hybrid_browser_used=bool(res.get("hybrid_browser_used")),
                    hybrid_blocked=bool(res.get("hybrid_blocked")),
                    hybrid_blocked_status=res.get("hybrid_blocked_status"),
                    backoff_minutes=minutes,
                    webmotors_diag=wm_diag,
                    dual_report=getattr(ctx, "_dual_run_report_path", None),
                )
                run_row = record_run(
                    db,
                    source=src,
                    kind=kind,
                    status="blocked",
                    url=res.get("url") or url,
                    http_status=res.get("status_code"),
                    duration_ms=duration_ms,
                    groups=groups_count,
                    wishlists=total_wishlists,
                    proxy_server=ctx.proxy_server,
                    browser_fallback_enabled=bool(ctx.browser_fallback_enabled),
                    force_browser=bool(ctx.force_browser),
                    error=f"blocked(backoff={minutes}m; browser_fallback={bool(res.get('hybrid_browser_used'))})",
                    payload=payload,
                )
                logger.info("source_run_summary", extra=run_summary_err)
                emit_event(
                    db,
                    level="warn",
                    event_type="source_blocked",
                    source=src,
                    run_id=run_row.id,
                    message="source_blocked",
                    evidence={"minutes": minutes, "url": res.get("url") or url, "http_status": res.get("status_code"), "kind": kind, "run_reason": reason},
                    tags=[kind, reason, "blocked"],
                )
                log(db, "warn", component, "backoff_applied", {"minutes": minutes, "url": res.get("url") or url}, source=src, run_id=run_row.id, event_type="source_blocked", tags=[kind, reason, "blocked"])
                db.commit()
                return {"ok": False, "status": "blocked", "backoff_minutes": minutes, "http_status": res.get("status_code"), "url": res.get("url") or url, "duration_ms": duration_ms, "run_reason": reason, "payload": payload}

            if bool(res.get("is_bug")):
                err = res.get("error") or "scrape_failed"
                duration_ms = int((datetime.now(timezone.utc) - t0).total_seconds() * 1000)
                minutes = mark_bug(db, src, error=err, url=res.get("url") or url)
                run_row = record_run(
                    db,
                    source=src,
                    kind=kind,
                    status="error",
                    url=res.get("url") or url,
                    duration_ms=duration_ms,
                    groups=groups_count,
                    wishlists=total_wishlists,
                    proxy_server=ctx.proxy_server,
                    browser_fallback_enabled=bool(ctx.browser_fallback_enabled),
                    force_browser=bool(ctx.force_browser),
                    error=f"{err} (bug_retry={minutes}m)",
                    payload=build_run_payload(
                        run_summary=run_summary_err,
                        run_reason=reason,
                        hybrid_browser_used=bool(res.get("hybrid_browser_used")),
                        hybrid_blocked=bool(res.get("hybrid_blocked")),
                        hybrid_blocked_status=res.get("hybrid_blocked_status"),
                        retry_minutes=minutes,
                        is_bug=True,
                        webmotors_diag=wm_diag,
                        dual_report=getattr(ctx, "_dual_run_report_path", None),
                    ),
                )
                logger.info("source_run_summary", extra=run_summary_err)
                emit_event(
                    db,
                    level="error",
                    event_type="scrape_failed_bug",
                    source=src,
                    run_id=run_row.id,
                    message="scrape_failed_bug",
                    evidence={"error": err, "url": res.get("url") or url, "retry_minutes": minutes, "kind": kind, "run_reason": reason},
                    tags=[kind, reason, "bug"],
                )
                log(
                    db,
                    "error",
                    component,
                    "scrape_failed_bug",
                    {"error": err, "url": res.get("url") or url, "retry_minutes": minutes},
                    source=src,
                    run_id=run_row.id,
                    event_type="scrape_failed_bug",
                    tags=[kind, reason, "bug"],
                )
                db.commit()
                return {"ok": False, "status": "error", "error": err, "backoff_minutes": minutes, "url": res.get("url") or url, "duration_ms": duration_ms, "run_reason": reason}

            err = res.get("error") or "scrape_failed"
            duration_ms = int((datetime.now(timezone.utc) - t0).total_seconds() * 1000)
            minutes = mark_error(
                db,
                src,
                base_cooldown_minutes=(max(int(cfg.cooldown_minutes or 0), 15) if (src or '').lower()=='webmotors' else max(int(cfg.cooldown_minutes or 0), 1)),
                error=err,
                url=res.get("url") or url,
            )
            run_row = record_run(
                db,
                source=src,
                kind=kind,
                status="error",
                url=res.get("url") or url,
                duration_ms=duration_ms,
                groups=groups_count,
                wishlists=total_wishlists,
                proxy_server=ctx.proxy_server,
                browser_fallback_enabled=bool(ctx.browser_fallback_enabled),
                force_browser=bool(ctx.force_browser),
                error=f"{err} (backoff={minutes}m)",
                payload=build_run_payload(
                    run_summary=run_summary_err,
                    run_reason=reason,
                    hybrid_browser_used=bool(res.get("hybrid_browser_used")),
                    hybrid_blocked=bool(res.get("hybrid_blocked")),
                    hybrid_blocked_status=res.get("hybrid_blocked_status"),
                    backoff_minutes=minutes,
                    webmotors_diag=wm_diag,
                    dual_report=getattr(ctx, "_dual_run_report_path", None),
                ),
            )
            logger.info("source_run_summary", extra=run_summary_err)
            emit_event(
                db,
                level="error",
                event_type="scrape_failed",
                source=src,
                run_id=run_row.id,
                message="scrape_failed",
                evidence={"error": err, "url": res.get("url") or url, "backoff_minutes": minutes, "kind": kind, "run_reason": reason},
                tags=[kind, reason, "error"],
            )
            log(db, "error", component, "scrape_failed", {"error": err, "url": res.get("url") or url, "backoff_minutes": minutes}, source=src, run_id=run_row.id, event_type="scrape_failed", tags=[kind, reason, "error"])
            db.commit()
            return {"ok": False, "status": "error", "error": err, "backoff_minutes": minutes, "url": res.get("url") or url, "duration_ms": duration_ms, "run_reason": reason}

        total_found += int(res.get("found") or 0)
        total_inserted += int(res.get("inserted") or 0)
        total_matched += int(res.get("matched") or 0)
        total_queued += int(res.get("queued") or 0)
        total_already_notified += int(res.get("already_notified") or 0)
        for k, v in (res.get("reason_buckets") or {}).items():
            total_reason_buckets[k] = int(total_reason_buckets.get(k, 0)) + int(v or 0)
        total_thumb_present += int(res.get("thumb_present") or 0)
        for wid, seen_items in (res.get("seen_identities_by_wishlist") or {}).items():
            bucket = seen_identities_by_wishlist.setdefault(str(wid), [])
            bucket.extend(seen_items or [])

    duration_ms = int((datetime.now(timezone.utc) - t0).total_seconds() * 1000)
    run_summary_ok = add_anomaly_notes(health.finalize(RunStatus.OK)).model_dump(mode="json")

    mark_success(
        db,
        src,
        rate_limit_seconds=int(cfg.rate_limit_seconds or 0),
        payload={"groups": len(groups), "found": total_found, "inserted": total_inserted, "matched": total_matched, "queued": total_queued, "already_notified": total_already_notified, "reason_buckets": total_reason_buckets, "thumb_present": total_thumb_present, "thumb_rate": (float(total_thumb_present) / float(total_found)) if total_found else 0.0, "hybrid_browser_used": any_hybrid_browser, "hybrid_blocked": any_hybrid_blocked, "hybrid_blocked_status": last_hybrid_blocked_status, "run_reason": reason},
    )
    run_row = record_run(
        db,
        source=src,
        kind=kind,
        status="success",
        duration_ms=duration_ms,
        groups=groups_count,
        wishlists=total_wishlists,
        items_found=total_found,
        items_ingested=total_inserted,
        items_matched=total_matched,
        notifications_queued=total_queued,
        proxy_server=ctx.proxy_server,
        browser_fallback_enabled=bool(ctx.browser_fallback_enabled),
        force_browser=bool(ctx.force_browser),
        payload=build_run_payload(
            run_summary=run_summary_ok,
            run_reason=reason,
            hybrid_browser_used=any_hybrid_browser,
            hybrid_blocked=any_hybrid_blocked,
            hybrid_blocked_status=last_hybrid_blocked_status,
            thumb_present=total_thumb_present,
            thumb_rate=(float(total_thumb_present) / float(total_found)) if total_found else 0.0,
        ),
    )

    activity_stats = reconcile_listing_activity_for_source_run(
        db,
        source_name=src,
        wishlist_seen={w.id: (seen_identities_by_wishlist.get(str(w.id)) or []) for w in wishlists},
        target_wishlist_ids=[w.id for w in wishlists],
        missing_threshold=int(settings.listing_inactive_missing_runs_threshold or 3),
        valid_run_id=run_row.id,
    )
    run_row.payload = {
        **(run_row.payload or {}),
        "activity": activity_stats.to_dict(),
        "activity_missing_threshold": int(settings.listing_inactive_missing_runs_threshold or 3),
    }
    logger.info("source_run_summary", extra=run_summary_ok)

    emit_event(
        db,
        level="info",
        event_type="run_ok",
        source=src,
        run_id=run_row.id,
        message="run_ok",
        evidence={"groups": groups_count, "wishlists": total_wishlists, "found": total_found, "inserted": total_inserted, "matched": total_matched, "queued": total_queued, "already_notified": total_already_notified, "reason_buckets": total_reason_buckets, "thumb_present": total_thumb_present, "thumb_rate": (float(total_thumb_present) / float(total_found)) if total_found else 0.0, "duration_ms": duration_ms, "kind": kind, "run_reason": reason, "activity": activity_stats.to_dict(), "activity_missing_threshold": int(settings.listing_inactive_missing_runs_threshold or 3)},
        tags=[kind, reason, "ok"],
    )

    log(db, "info", component, "run_ok", {"groups": groups_count, "found": total_found, "inserted": total_inserted, "queued": total_queued, "already_notified": total_already_notified, "reason_buckets": total_reason_buckets, "run_reason": reason, "activity": activity_stats.to_dict(), "activity_missing_threshold": int(settings.listing_inactive_missing_runs_threshold or 3)}, source=src, run_id=run_row.id, event_type="run_ok", tags=[kind, reason, "ok"])

    db.commit()
    return {"ok": True, "status": "success", "duration_ms": duration_ms, "groups": len(groups), "found": total_found, "inserted": total_inserted, "matched": total_matched, "queued": total_queued, "already_notified": total_already_notified, "reason_buckets": total_reason_buckets, "run_summary": run_summary_ok, "run_reason": reason, "activity": activity_stats.to_dict(), "activity_missing_threshold": int(settings.listing_inactive_missing_runs_threshold or 3)}
