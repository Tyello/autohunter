from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session, joinedload
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
from app.services.wishlist_sources_service import allowed_sources_for_wishlists
from app.sources.registry import get_source
from app.sources.adapters.v1 import adapt_v1
from app.sources.adapters.v2 import adapt_v2
from app.sources.dual_run import execute_dual_run
from app.sources.flags import read_source_impl_flags
from app.sources.media import derive_thumbnail_url
from app.sources.normalize import (
    normalize_fuel_type,
    normalize_listing_type,
    normalize_seller_type,
    normalize_transmission,
)
from app.scrapers.sources import get_scraper
from app.health.collector import HealthCollector
from app.health.classify import classify_error
from app.health.explain import add_anomaly_notes
from app.health.models import RunStatus


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


def _get_state(db: Session, source: str) -> Optional[SourceState]:
    return db.execute(select(SourceState).where(SourceState.source == source)).scalar_one_or_none()


def _get_cfg(db: Session, source: str) -> Optional[SourceConfig]:
    return db.execute(select(SourceConfig).where(SourceConfig.source == source)).scalar_one_or_none()


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
        last_eff = st.last_effective_run_at if st else None
        if last_eff and (_utcnow() - last_eff) < timedelta(minutes=minutes):
            return {"ok": True, "status": "skipped", "reason": "not_due", "run_reason": reason}

    # Feed sources (maintenance/inventory) can run without wishlists.
    if not bool(getattr(plugin, "supports_wishlist_monitoring", True)):
        url = plugin.build_url("")
        groups: dict[str, dict] = {url: {"query": None, "wishlists": []}}
        wishlists = []
    else:
        wishlists = (
            db.query(Wishlist)
            .options(joinedload(Wishlist.filters))
            .filter(Wishlist.is_active == True)
            .all()
        )
        if not wishlists:
            log(db, "info", component, "no_active_wishlists")
            db.commit()
            return {"ok": True, "status": "skipped", "reason": "no_active_wishlists", "run_reason": reason}

        groups = {}
        allowed_map = allowed_sources_for_wishlists(db, wishlists)
        for w in wishlists:
            sources = allowed_map.get(w.id) or set()
            if src not in sources:
                continue
            url = plugin.build_url(w.query)
            g = groups.get(url)
            if g is None:
                groups[url] = {"query": w.query, "wishlists": [w]}
            else:
                g["wishlists"].append(w)

        if not groups:
            log(db, "info", component, "no_matching_wishlists")
            db.commit()
            return {"ok": True, "status": "skipped", "reason": "no_matching_wishlists", "run_reason": reason}

    ctx = build_scrape_context(db, src)
    flags = read_source_impl_flags(cfg.extra)
    v2_scraper = get_scraper(src)

    def _scrape_dispatch(search_url: str, ctx):
        if flags.impl == "v2" and v2_scraper is not None:
            result = v2_scraper.scrape(search_url, ctx)
            ads, _meta = adapt_v2(src, result)
            return [_ad_to_listing(ad) for ad in ads if ad.external_id]
        if flags.impl == "dual" and v2_scraper is not None:
            chosen, report = execute_dual_run(
                source=src,
                search_url=search_url,
                ctx=ctx,
                v1_scrape_fn=plugin.scrape,
                v2_scraper=v2_scraper,
                flags=flags,
            )
            object.__setattr__(ctx, "_dual_run_summary", report.get("comparison") or {})
            ads, _meta = adapt_v1(src, chosen)
            return [_ad_to_listing(ad) for ad in ads if ad.external_id]
        raw = plugin.scrape(search_url, ctx=ctx)
        ads, _meta = adapt_v1(src, raw)
        return [_ad_to_listing(ad) for ad in ads if ad.external_id]

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
                health.inc("blocked", 1)
            else:
                category, status_cls, retryable, http_status, bucket = classify_error(Exception(str(res.get("error") or reason)))
            health.inc("errors", 1)
            health.count(bucket, 1)
            health.set_error(category, str(res.get("error") or reason), http_status=http_status, retryable=retryable)
            run_summary_err = add_anomaly_notes(health.finalize(status_cls)).model_dump(mode="json")
            if reason == "blocked":
                minutes = mark_blocked(
                    db,
                    src,
                    base_cooldown_minutes=(max(int(cfg.cooldown_minutes or 0), 15) if (src or '').lower()=='webmotors' else max(int(cfg.cooldown_minutes or 0), 1)),
                    http_status=res.get("status_code"),
                    url=res.get("url") or url,
                )
                run_row = record_run(
                    db,
                    source=src,
                    kind=kind,
                    status="blocked",
                    url=res.get("url") or url,
                    http_status=res.get("status_code"),
                    duration_ms=int((datetime.now(timezone.utc) - t0).total_seconds() * 1000),
                    groups=groups_count,
                    wishlists=total_wishlists,
                    proxy_server=ctx.proxy_server,
                    browser_fallback_enabled=bool(ctx.browser_fallback_enabled),
                    force_browser=bool(ctx.force_browser),
                    error=f"blocked(backoff={minutes}m; browser_fallback={bool(res.get('hybrid_browser_used'))})",
                    payload={"backoff_minutes": minutes, "hybrid_browser_used": bool(res.get("hybrid_browser_used")), "hybrid_blocked": bool(res.get("hybrid_blocked")), "hybrid_blocked_status": res.get("hybrid_blocked_status"), "dual_report": getattr(ctx, "_dual_run_report_path", None), "run_summary": run_summary_err, "run_reason": reason},
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
                return {"ok": False, "status": "blocked", "backoff_minutes": minutes, "http_status": res.get("status_code"), "url": res.get("url") or url, "run_reason": reason}

            if bool(res.get("is_bug")):
                err = res.get("error") or "scrape_failed"
                minutes = mark_bug(db, src, error=err, url=res.get("url") or url)
                run_row = record_run(
                    db,
                    source=src,
                    kind=kind,
                    status="error",
                    url=res.get("url") or url,
                    duration_ms=int((datetime.now(timezone.utc) - t0).total_seconds() * 1000),
                    groups=groups_count,
                    wishlists=total_wishlists,
                    proxy_server=ctx.proxy_server,
                    browser_fallback_enabled=bool(ctx.browser_fallback_enabled),
                    force_browser=bool(ctx.force_browser),
                    error=f"{err} (bug_retry={minutes}m)",
                    payload={"retry_minutes": minutes, "is_bug": True, "hybrid_browser_used": bool(res.get("hybrid_browser_used")), "hybrid_blocked": bool(res.get("hybrid_blocked")), "hybrid_blocked_status": res.get("hybrid_blocked_status"), "dual_report": getattr(ctx, "_dual_run_report_path", None), "run_summary": run_summary_err, "run_reason": reason},
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
                return {"ok": False, "status": "error", "error": err, "backoff_minutes": minutes, "url": res.get("url") or url, "run_reason": reason}

            err = res.get("error") or "scrape_failed"
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
                duration_ms=int((datetime.now(timezone.utc) - t0).total_seconds() * 1000),
                groups=groups_count,
                wishlists=total_wishlists,
                proxy_server=ctx.proxy_server,
                browser_fallback_enabled=bool(ctx.browser_fallback_enabled),
                force_browser=bool(ctx.force_browser),
                error=f"{err} (backoff={minutes}m)",
                payload={"backoff_minutes": minutes, "hybrid_browser_used": bool(res.get("hybrid_browser_used")), "hybrid_blocked": bool(res.get("hybrid_blocked")), "hybrid_blocked_status": res.get("hybrid_blocked_status"), "dual_report": getattr(ctx, "_dual_run_report_path", None), "run_summary": run_summary_err, "run_reason": reason},
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
            return {"ok": False, "status": "error", "error": err, "backoff_minutes": minutes, "url": res.get("url") or url, "run_reason": reason}

        total_found += int(res.get("found") or 0)
        total_inserted += int(res.get("inserted") or 0)
        total_matched += int(res.get("matched") or 0)
        total_queued += int(res.get("queued") or 0)
        total_already_notified += int(res.get("already_notified") or 0)
        for k, v in (res.get("reason_buckets") or {}).items():
            total_reason_buckets[k] = int(total_reason_buckets.get(k, 0)) + int(v or 0)
        total_thumb_present += int(res.get("thumb_present") or 0)

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
        payload={"hybrid_browser_used": any_hybrid_browser, "hybrid_blocked": any_hybrid_blocked, "hybrid_blocked_status": last_hybrid_blocked_status, "thumb_present": total_thumb_present, "thumb_rate": (float(total_thumb_present) / float(total_found)) if total_found else 0.0, "run_summary": run_summary_ok, "run_reason": reason},
    )
    logger.info("source_run_summary", extra=run_summary_ok)

    emit_event(
        db,
        level="info",
        event_type="run_ok",
        source=src,
        run_id=run_row.id,
        message="run_ok",
        evidence={"groups": groups_count, "wishlists": total_wishlists, "found": total_found, "inserted": total_inserted, "matched": total_matched, "queued": total_queued, "already_notified": total_already_notified, "reason_buckets": total_reason_buckets, "thumb_present": total_thumb_present, "thumb_rate": (float(total_thumb_present) / float(total_found)) if total_found else 0.0, "duration_ms": duration_ms, "kind": kind, "run_reason": reason},
        tags=[kind, reason, "ok"],
    )

    log(db, "info", component, "run_ok", {"groups": groups_count, "found": total_found, "inserted": total_inserted, "queued": total_queued, "already_notified": total_already_notified, "reason_buckets": total_reason_buckets, "run_reason": reason}, source=src, run_id=run_row.id, event_type="run_ok", tags=[kind, reason, "ok"])

    db.commit()
    return {"ok": True, "status": "success", "duration_ms": duration_ms, "groups": len(groups), "found": total_found, "inserted": total_inserted, "matched": total_matched, "queued": total_queued, "already_notified": total_already_notified, "reason_buckets": total_reason_buckets, "run_summary": run_summary_ok, "run_reason": reason}
