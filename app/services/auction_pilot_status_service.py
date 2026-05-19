from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, func

from app.models.app_kv import AppKV
from app.models.source_config import SourceConfig
from app.models.system_log import SystemLog
from app.models.wishlist import Wishlist
from app.services.auction_notification_settings_service import get_auction_notification_runtime_settings
from app.services.auction_notification_readiness_service import build_auction_notification_readiness
from app.services.auction_source_categories_service import get_auction_allowed_item_types


MANUAL_REAL_EVENTS = ("auction_notification_manual_real_run_finished", "auction_notification_manual_real_run_failed")
DRY_RUN_EVENTS = ("auction_notification_scheduler_tick_finished", "auction_notification_scheduler_tick_skipped")


def _check(key: str, status: str, label: str, detail: str) -> dict:
    return {"key": key, "status": status, "label": label, "detail": detail}


def _to_utc_text(dt: datetime | None) -> str | None:
    if not dt:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def build_auction_pilot_status(db) -> dict:
    cfg = get_auction_notification_runtime_settings(db)
    now = datetime.now(timezone.utc)
    since_24h = now - timedelta(hours=24)

    scheduler_enabled = bool(cfg.get("enabled"))
    scheduler_dry_run = bool(cfg.get("dry_run"))
    automatic_real_active = scheduler_enabled and not scheduler_dry_run

    eligible_rows = (
        db.query(SourceConfig)
        .filter(SourceConfig.source_type == "auction", SourceConfig.is_enabled.is_(True), SourceConfig.user_eligible.is_(True))
        .all()
    )
    user_eligible = sorted({row.source for row in eligible_rows if row.source})

    readiness = build_auction_notification_readiness(db)
    summary = readiness.get("summary") if isinstance(readiness, dict) else {}
    ready_car_pilot = sorted(summary.get("car_pilot_ready_sources") or [])

    all_enabled = (
        db.query(SourceConfig.source)
        .filter(SourceConfig.source_type == "auction", SourceConfig.is_enabled.is_(True))
        .all()
    )
    experimental_enabled = sorted([s for (s,) in all_enabled if s and s not in {"vip_auctions"}])
    unsafe_user_eligible = sorted([s for s in user_eligible if s != "vip_auctions"])

    active_total = int(db.query(Wishlist).filter(Wishlist.is_active.is_(True)).count())
    include_auctions_total = int(db.query(Wishlist).filter(Wishlist.is_active.is_(True), Wishlist.include_auctions.is_(True)).count())
    users_with_auction_wishlists = int(
        db.query(func.count(func.distinct(Wishlist.user_id))).filter(Wishlist.is_active.is_(True), Wishlist.include_auctions.is_(True)).scalar() or 0
    )

    manual_rows = (
        db.query(SystemLog)
        .filter(SystemLog.message.in_(MANUAL_REAL_EVENTS))
        .order_by(SystemLog.created_at.desc())
        .all()
    )
    last_manual = manual_rows[0] if manual_rows else None
    last_payload = (last_manual.payload or {}) if last_manual else {}
    rows_24h = [r for r in manual_rows if r.created_at and (r.created_at if r.created_at.tzinfo else r.created_at.replace(tzinfo=timezone.utc)) >= since_24h]

    manual_real_sent_24h = 0
    duplicates_24h = 0
    errors_24h = 0
    for row in rows_24h:
        payload = row.payload if isinstance(row.payload, dict) else {}
        manual_real_sent_24h += int(payload.get("sent") or 0)
        duplicates_24h += int(payload.get("skipped_duplicate") or 0)
        errors_24h += int(payload.get("errors") or 0)

    dry_runs = (
        db.query(SystemLog)
        .filter(SystemLog.component == "scheduler", SystemLog.message.in_(DRY_RUN_EVENTS), SystemLog.created_at >= since_24h)
        .all()
    )
    dry_run_previews_24h = 0
    rejection_counter: Counter[str] = Counter()
    for row in dry_runs:
        payload = row.payload if isinstance(row.payload, dict) else {}
        dry_run_previews_24h += int(payload.get("previews") or 0)
        for rej in (payload.get("rejections") or []):
            reason = str((rej or {}).get("reason") or "").strip().lower()
            if reason:
                rejection_counter[reason] += 1

    last_dry = db.query(AppKV).filter(AppKV.key == "auction_last_dry_run_samples").first()
    dry_data = last_dry.value if last_dry and isinstance(last_dry.value, dict) else {}
    dry_last_previews = int(((dry_data.get("summary") or {}).get("previews")) or len(dry_data.get("samples") or []))
    dry_last_at = dry_data.get("created_at")
    dry_history_partial = False
    if dry_run_previews_24h <= 0 and dry_last_previews > 0:
        dry_history_partial = True

    checks = []
    vip_allowed = set(get_auction_allowed_item_types(db, "vip_auctions"))
    if unsafe_user_eligible:
        checks.append(_check("vip_only_user_eligible", "warning", "VIP é a única source user-facing", f"Sources expostas: {', '.join(unsafe_user_eligible)}"))
    else:
        checks.append(_check("vip_only_user_eligible", "ok", "VIP é a única source user-facing", "Apenas vip_auctions está user_eligible=true"))
    if "vip_auctions" not in user_eligible:
        checks.append(_check("vip_user_eligible", "warning", "VIP user_eligible", "vip_auctions não está user_eligible=true"))
    else:
        checks.append(_check("vip_user_eligible", "ok", "VIP user_eligible", "vip_auctions está user_eligible=true"))
    if "car" not in vip_allowed:
        checks.append(_check("vip_car_category", "warning", "VIP categoria car", "vip_auctions não permite categoria car"))
    else:
        checks.append(_check("vip_car_category", "ok", "VIP categoria car", "categoria car permitida"))
    if automatic_real_active:
        checks.append(_check("automatic_real_active", "blocked", "Scheduler automático real desligado", "enabled=true e dry_run=false"))
    else:
        checks.append(_check("automatic_real_active", "ok", "Scheduler automático real desligado", "dry_run=true ou enabled=false"))
    if include_auctions_total <= 0:
        checks.append(_check("adoption", "warning", "Buscas com leilões ativados", "Nenhuma busca ativa com include_auctions=true"))
    else:
        checks.append(_check("adoption", "ok", "Buscas com leilões ativados", str(include_auctions_total)))
    if not ready_car_pilot:
        checks.append(_check("ready_car_pilot", "warning", "Source pronta para piloto car", "Nenhuma source pronta para piloto car"))
    else:
        checks.append(_check("ready_car_pilot", "ok", "Source pronta para piloto car", ", ".join(ready_car_pilot)))

    statuses = {c["status"] for c in checks}
    health_status = "blocked" if "blocked" in statuses else ("warning" if "warning" in statuses else "ok")

    return {
        "mode": {
            "scheduler_enabled": scheduler_enabled,
            "scheduler_dry_run": scheduler_dry_run,
            "manual_real_available": ("vip_auctions" in user_eligible and "vip_auctions" in ready_car_pilot and "car" in vip_allowed),
            "automatic_real_active": automatic_real_active,
        },
        "sources": {
            "user_eligible": user_eligible,
            "ready_car_pilot": ready_car_pilot,
            "experimental_enabled": experimental_enabled,
            "unsafe_user_eligible": unsafe_user_eligible,
        },
        "wishlists": {
            "active_total": active_total,
            "include_auctions_total": include_auctions_total,
            "users_with_auction_wishlists": users_with_auction_wishlists,
        },
        "notifications": {
            "last_manual_real_at": _to_utc_text(last_manual.created_at) if last_manual else None,
            "last_manual_real_sent": int(last_payload.get("sent") or 0),
            "last_manual_real_duplicates": int(last_payload.get("skipped_duplicate") or 0),
            "last_manual_real_errors": int(last_payload.get("errors") or 0),
            "manual_real_runs_24h": len(rows_24h),
            "manual_real_sent_24h": manual_real_sent_24h,
            "duplicates_24h": duplicates_24h,
            "errors_24h": errors_24h,
            "dry_run_previews_24h": dry_run_previews_24h,
            "last_dry_run_at": dry_last_at,
            "last_dry_run_previews": dry_last_previews,
            "dry_run_history_partial": dry_history_partial,
            "top_rejections": [k for k, _ in rejection_counter.most_common(3)],
        },
        "health": {"status": health_status, "checks": checks},
    }
