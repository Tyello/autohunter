from __future__ import annotations

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
from app.services.source_backoff_service import is_source_allowed, mark_blocked, mark_error, mark_success, mark_skipped
from app.services.source_configs_service import ensure_source_configs, build_scrape_context
from app.services.source_runs_service import record_run
from app.services.wishlist_sources_service import allowed_sources_for_wishlist
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
        record_run(db, source=src, kind=kind, status="skipped", payload={"reason": "playwright_off"})
        return {"ok": True, "status": "skipped", "reason": "playwright_off"}

    # Backoff checks
    if not force:
        avail = is_source_allowed(db, src)
        if not avail.is_allowed:
            mark_skipped(db, src, "backoff", {"next_allowed_at": str(avail.next_allowed_at) if avail.next_allowed_at else None})
            record_run(db, source=src, kind=kind, status="skipped", payload={"reason": "backoff", "next_allowed_at": str(avail.next_allowed_at) if avail.next_allowed_at else None})
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

    wishlists = db.query(Wishlist).filter(Wishlist.is_active == True).all()
    if not wishlists:
        return {"ok": True, "status": "skipped", "reason": "no_active_wishlists"}

    groups: dict[str, dict] = {}
    for w in wishlists:
        sources = allowed_sources_for_wishlist(db, w.id)
        if src not in sources:
            continue
        url = plugin.build_url(w.query)
        g = groups.get(url)
        if g is None:
            groups[url] = {"query": w.query, "wishlists": [w]}
        else:
            g["wishlists"].append(w)

    if not groups:
        return {"ok": True, "status": "skipped", "reason": "no_matching_wishlists"}

    ctx = build_scrape_context(db, src)

    t0 = datetime.now(timezone.utc)
    total_found = 0
    total_inserted = 0
    total_matched = 0
    total_queued = 0

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
                record_run(
                    db,
                    source=src,
                    kind=kind,
                    status="blocked",
                    url=res.get("url") or url,
                    http_status=res.get("status_code"),
                    duration_ms=int((datetime.now(timezone.utc) - t0).total_seconds() * 1000),
                    error=f"blocked(backoff={minutes}m)",
                )
                log(db, "warn", component, "backoff_applied", {"minutes": minutes, "url": res.get("url") or url})
                return {"ok": False, "status": "blocked", "backoff_minutes": minutes, "http_status": res.get("status_code"), "url": res.get("url") or url}

            err = res.get("error") or "scrape_failed"
            minutes = mark_error(
                db,
                src,
                base_cooldown_minutes=max(int(cfg.cooldown_minutes or 0), 1),
                error=err,
                url=res.get("url") or url,
            )
            record_run(
                db,
                source=src,
                kind=kind,
                status="error",
                url=res.get("url") or url,
                duration_ms=int((datetime.now(timezone.utc) - t0).total_seconds() * 1000),
                error=f"{err} (backoff={minutes}m)",
            )
            log(db, "error", component, "scrape_failed", {"error": err, "url": res.get("url") or url, "backoff_minutes": minutes})
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
        payload={"groups": len(groups), "found": total_found, "inserted": total_inserted, "matched": total_matched, "queued": total_queued},
    )
    record_run(
        db,
        source=src,
        kind=kind,
        status="success",
        duration_ms=duration_ms,
        items_found=total_found,
        items_ingested=total_inserted,
        matches_found=total_matched,
        notifications_queued=total_queued,
    )

    log(db, "info", component, "run_ok", {"groups": len(groups), "found": total_found, "inserted": total_inserted, "queued": total_queued})

    return {"ok": True, "status": "success", "duration_ms": duration_ms, "groups": len(groups), "found": total_found, "inserted": total_inserted, "matched": total_matched, "queued": total_queued}
