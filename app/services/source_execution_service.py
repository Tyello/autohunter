from __future__ import annotations

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

    if not plugin:
        return {"ok": False, "status": "error", "error": f"unknown_source:{src}"}

    # Ensure DB rows exist (seed defaults once)
    ensure_source_configs(db)

    cfg = _get_cfg(db, src)
    if not cfg:
        return {"ok": False, "status": "error", "error": f"missing_source_config:{src}"}

    # Disabled?
    if not force and not bool(cfg.is_enabled):
        return {"ok": True, "status": "skipped", "reason": "disabled"}

    # Not implemented?
    if plugin.scrape is None:
        if not force:
            return {"ok": True, "status": "skipped", "reason": "not_implemented"}
        return {"ok": False, "status": "error", "error": "not_implemented"}

    # Playwright checks
    if (plugin.fetch_mode == "browser" or bool(cfg.force_browser)) and not bool(settings.enable_playwright):
        mark_skipped(db, src, "playwright_off")
        run_row = record_run(
            db,
            source=src,
            kind=kind,
            status="skipped",
            payload={"reason": "playwright_off"},
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
            evidence={"reason": "playwright_off", "kind": kind},
            tags=[kind, "ops"],
        )
        log(db, "warn", component, "playwright_off", source=src, run_id=run_row.id, event_type="playwright_off", tags=[kind, "ops"])
        db.commit()
        return {"ok": True, "status": "skipped", "reason": "playwright_off"}

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
                payload={"reason": "backoff", "next_allowed_at": str(avail.next_allowed_at) if avail.next_allowed_at else None},
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
                evidence={"next_allowed_at": str(avail.next_allowed_at) if avail.next_allowed_at else None, "kind": kind},
                tags=[kind, "ops"],
            )
            log(db, "info", component, "skipped_backoff", {"next_allowed_at": str(avail.next_allowed_at) if avail.next_allowed_at else None}, source=src, run_id=run_row.id, event_type="skipped_backoff", tags=[kind, "ops"])
            db.commit()
            return {"ok": True, "status": "skipped", "reason": "backoff", "next_allowed_at": avail.next_allowed_at}

    # Schedule / due checks (based on last_effective_run_at)
    if not force:
        minutes = int(cfg.sched_minutes or 0)
        if minutes <= 0:
            return {"ok": True, "status": "skipped", "reason": "sched_0"}

        st = _get_state(db, src)
        last_eff = st.last_effective_run_at if st else None
        if last_eff and (_utcnow() - last_eff) < timedelta(minutes=minutes):
            return {"ok": True, "status": "skipped", "reason": "not_due"}

    wishlists = (
        db.query(Wishlist)
        .options(joinedload(Wishlist.filters))
        .filter(Wishlist.is_active == True)
        .all()
    )
    if not wishlists:
        log(db, "info", component, "no_active_wishlists")
        db.commit()
        return {"ok": True, "status": "skipped", "reason": "no_active_wishlists"}

    groups: dict[str, dict] = {}
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
        return {"ok": True, "status": "skipped", "reason": "no_matching_wishlists"}

    ctx = build_scrape_context(db, src)

    groups_count = len(groups)
    total_wishlists = sum(len(g.get("wishlists") or []) for g in groups.values())

    t0 = datetime.now(timezone.utc)
    total_found = 0
    total_inserted = 0
    total_matched = 0
    total_queued = 0
    any_hybrid_browser = False
    any_hybrid_blocked = False
    last_hybrid_blocked_status: int | None = None

    for url, g in groups.items():
        job_name = f"scraper_{src}"
        res = scrape_ingest_match_many(
            db,
            job_name,
            plugin.scrape,
            url,
            ctx=ctx,
            wishlists=g["wishlists"],
        )

        any_hybrid_browser = any_hybrid_browser or bool(res.get("hybrid_browser_used"))
        any_hybrid_blocked = any_hybrid_blocked or bool(res.get("hybrid_blocked"))
        if res.get("hybrid_blocked_status") is not None:
            last_hybrid_blocked_status = int(res.get("hybrid_blocked_status"))

        if not res.get("ok"):
            reason = res.get("reason") or "error"
            if reason == "blocked":
                minutes = mark_blocked(
                    db,
                    src,
                    base_cooldown_minutes=max(int(cfg.cooldown_minutes or 0), 1),
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
                    payload={"backoff_minutes": minutes, "hybrid_browser_used": bool(res.get("hybrid_browser_used")), "hybrid_blocked": bool(res.get("hybrid_blocked")), "hybrid_blocked_status": res.get("hybrid_blocked_status")},
                )
                emit_event(
                    db,
                    level="warn",
                    event_type="source_blocked",
                    source=src,
                    run_id=run_row.id,
                    message="source_blocked",
                    evidence={"minutes": minutes, "url": res.get("url") or url, "http_status": res.get("status_code"), "kind": kind},
                    tags=[kind, "blocked"],
                )
                log(db, "warn", component, "backoff_applied", {"minutes": minutes, "url": res.get("url") or url}, source=src, run_id=run_row.id, event_type="source_blocked", tags=[kind, "blocked"])
                db.commit()
                return {"ok": False, "status": "blocked", "backoff_minutes": minutes, "http_status": res.get("status_code"), "url": res.get("url") or url}

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
                    payload={"retry_minutes": minutes, "is_bug": True, "hybrid_browser_used": bool(res.get("hybrid_browser_used")), "hybrid_blocked": bool(res.get("hybrid_blocked")), "hybrid_blocked_status": res.get("hybrid_blocked_status")},
                )
                emit_event(
                    db,
                    level="error",
                    event_type="scrape_failed_bug",
                    source=src,
                    run_id=run_row.id,
                    message="scrape_failed_bug",
                    evidence={"error": err, "url": res.get("url") or url, "retry_minutes": minutes, "kind": kind},
                    tags=[kind, "bug"],
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
                    tags=[kind, "bug"],
                )
                db.commit()
                return {"ok": False, "status": "error", "error": err, "backoff_minutes": minutes, "url": res.get("url") or url}

            err = res.get("error") or "scrape_failed"
            minutes = mark_error(
                db,
                src,
                base_cooldown_minutes=max(int(cfg.cooldown_minutes or 0), 1),
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
                payload={"backoff_minutes": minutes, "hybrid_browser_used": bool(res.get("hybrid_browser_used")), "hybrid_blocked": bool(res.get("hybrid_blocked")), "hybrid_blocked_status": res.get("hybrid_blocked_status")},
            )
            emit_event(
                db,
                level="error",
                event_type="scrape_failed",
                source=src,
                run_id=run_row.id,
                message="scrape_failed",
                evidence={"error": err, "url": res.get("url") or url, "backoff_minutes": minutes, "kind": kind},
                tags=[kind, "error"],
            )
            log(db, "error", component, "scrape_failed", {"error": err, "url": res.get("url") or url, "backoff_minutes": minutes}, source=src, run_id=run_row.id, event_type="scrape_failed", tags=[kind, "error"])
            db.commit()
            return {"ok": False, "status": "error", "error": err, "backoff_minutes": minutes, "url": res.get("url") or url}

        total_found += int(res.get("found") or 0)
        total_inserted += int(res.get("inserted") or 0)
        total_matched += int(res.get("matched") or 0)
        total_queued += int(res.get("queued") or 0)

    duration_ms = int((datetime.now(timezone.utc) - t0).total_seconds() * 1000)

    mark_success(
        db,
        src,
        rate_limit_seconds=int(cfg.rate_limit_seconds or 0),
        payload={"groups": len(groups), "found": total_found, "inserted": total_inserted, "matched": total_matched, "queued": total_queued, "hybrid_browser_used": any_hybrid_browser, "hybrid_blocked": any_hybrid_blocked, "hybrid_blocked_status": last_hybrid_blocked_status},
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
        payload={"hybrid_browser_used": any_hybrid_browser, "hybrid_blocked": any_hybrid_blocked, "hybrid_blocked_status": last_hybrid_blocked_status},
    )

    emit_event(
        db,
        level="info",
        event_type="run_ok",
        source=src,
        run_id=run_row.id,
        message="run_ok",
        evidence={"groups": groups_count, "wishlists": total_wishlists, "found": total_found, "inserted": total_inserted, "matched": total_matched, "queued": total_queued, "duration_ms": duration_ms, "kind": kind},
        tags=[kind, "ok"],
    )

    log(db, "info", component, "run_ok", {"groups": groups_count, "found": total_found, "inserted": total_inserted, "queued": total_queued}, source=src, run_id=run_row.id, event_type="run_ok", tags=[kind, "ok"])

    db.commit()
    return {"ok": True, "status": "success", "duration_ms": duration_ms, "groups": len(groups), "found": total_found, "inserted": total_inserted, "matched": total_matched, "queued": total_queued}
