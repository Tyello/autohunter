from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, or_

from app.core.settings import settings
from app.models.app_kv import AppKV
from app.models.auction_lot import AuctionLot
from app.models.source_config import SourceConfig
from app.models.system_log import SystemLog
from app.models.wishlist import Wishlist

_SCHEDULER_EVENTS = (
    "auction_notification_scheduler_tick_finished",
    "auction_notification_scheduler_tick_skipped",
    "auction_notification_scheduler_tick_failed",
)


def _check(key: str, status: str, label: str, detail: str) -> dict:
    return {"key": key, "status": status, "label": label, "detail": detail}


def build_auction_notification_readiness(db) -> dict:
    enabled = bool(getattr(settings, "auction_notifications_enabled", False))
    dry_run = bool(getattr(settings, "auction_notifications_dry_run", True))
    min_score = int(getattr(settings, "auction_notifications_min_score_safe", 60) or 60)
    max_lot_age_hours = int(getattr(settings, "auction_notifications_max_lot_age_hours_safe", 48) or 0)
    max_per_user_per_day = int(getattr(settings, "auction_notifications_max_per_user_per_day", 3) or 3)
    max_per_wishlist = int(getattr(settings, "auction_notifications_max_per_wishlist", 1) or 1)
    max_wishlists = int(getattr(settings, "auction_notifications_max_wishlists_per_run", 20) or 20)

    checks: list[dict] = []

    if enabled and not dry_run:
        checks.append(_check("safe_config", "fail", "Envio automático real desligado", "AUCTION_NOTIFICATIONS_ENABLED=true e AUCTION_NOTIFICATIONS_DRY_RUN=false"))
    else:
        checks.append(_check("safe_config", "ok", "Envio automático real desligado", f"enabled={'true' if enabled else 'false'}, dry_run={'true' if dry_run else 'false'}"))

    eligible_sources = (
        db.query(SourceConfig)
        .filter(SourceConfig.source_type == "auction", SourceConfig.is_enabled.is_(True), SourceConfig.user_eligible.is_(True))
        .all()
    )
    eligible_source_keys = sorted([s.source for s in eligible_sources])
    if not eligible_source_keys:
        checks.append(_check("eligible_sources", "fail", "Source elegível disponível", "Nenhuma source de leilão elegível para usuário."))
    else:
        checks.append(_check("eligible_sources", "ok", "Source elegível disponível", ", ".join(eligible_source_keys)))

    vip_cfg = db.query(SourceConfig).filter(SourceConfig.source == "vip_auctions", SourceConfig.source_type == "auction").first()
    if vip_cfg and vip_cfg.user_eligible:
        checks.append(_check("vip_operational", "ok", "VIP operacional", "vip_auctions com user_eligible=true"))
    elif vip_cfg:
        checks.append(_check("vip_operational", "warn", "VIP operacional", "vip_auctions existe mas não está user_eligible=true"))
    else:
        checks.append(_check("vip_operational", "warn", "VIP operacional", "vip_auctions não encontrada em source_configs"))

    wishlists_opt_in = int(db.query(Wishlist).filter(Wishlist.is_active.is_(True), Wishlist.include_auctions.is_(True)).count())
    if wishlists_opt_in <= 0:
        checks.append(_check("wishlists_opt_in", "warn", "Buscas com leilões ativados", "Nenhuma busca com leilões ativados."))
    else:
        checks.append(_check("wishlists_opt_in", "ok", "Buscas com leilões ativados", str(wishlists_opt_in)))

    recent_with_bid = 0
    if eligible_source_keys:
        threshold = datetime.now(timezone.utc) - timedelta(hours=max_lot_age_hours if max_lot_age_hours > 0 else 48)
        recent_with_bid = int(
            db.query(AuctionLot)
            .filter(
                AuctionLot.source.in_(eligible_source_keys),
                AuctionLot.url.isnot(None),
                AuctionLot.url != "",
                or_(AuctionLot.current_bid.isnot(None), AuctionLot.initial_bid.isnot(None)),
                AuctionLot.updated_at.isnot(None),
                AuctionLot.updated_at >= threshold,
            )
            .count()
        )
    if recent_with_bid <= 0:
        checks.append(_check("recent_eligible_lots", "warn", "Lotes recentes com lance", "Nenhum lote recente com lance nas sources elegíveis."))
    else:
        checks.append(_check("recent_eligible_lots", "ok", "Lotes recentes com lance", str(recent_with_bid)))

    last_scheduler = (
        db.query(SystemLog)
        .filter(SystemLog.component == "scheduler", SystemLog.message.in_(_SCHEDULER_EVENTS))
        .order_by(SystemLog.created_at.desc())
        .first()
    )
    scheduler_last_run_at = "-"
    scheduler_last_status = "missing"
    if not last_scheduler:
        checks.append(_check("scheduler_last_execution", "warn", "Última execução do scheduler", "Scheduler de leilões ainda não registrou execução."))
    else:
        scheduler_last_run_at = last_scheduler.created_at.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC") if last_scheduler.created_at else "-"
        if last_scheduler.message == "auction_notification_scheduler_tick_failed" or (last_scheduler.level or "").lower() == "error":
            scheduler_last_status = "failed"
            checks.append(_check("scheduler_last_execution", "fail", "Última execução do scheduler", f"Falha em {scheduler_last_run_at}"))
        else:
            scheduler_last_status = "ok"
            checks.append(_check("scheduler_last_execution", "ok", "Última execução do scheduler", scheduler_last_run_at))

    samples = db.query(AppKV).filter(AppKV.key == "auction_last_dry_run_samples").first()
    sample_count = 0
    if samples and isinstance(samples.value, dict):
        sample_count = len(samples.value.get("samples") or [])
    if sample_count <= 0:
        checks.append(_check("dry_run_samples", "warn", "Amostras de dry-run", "Nenhuma amostra de dry-run registrada."))
    else:
        checks.append(_check("dry_run_samples", "ok", "Amostras de dry-run", f"{sample_count} amostras"))

    gates_warn = []
    if min_score < 50:
        gates_warn.append("min_score < 50")
    if max_lot_age_hours <= 0 or max_lot_age_hours > 72:
        gates_warn.append("max_lot_age_hours fora de (0,72]")
    if max_per_user_per_day > 3:
        gates_warn.append("max_per_user_per_day > 3")
    if max_per_wishlist not in (1, 2):
        gates_warn.append("max_per_wishlist fora de 1..2")
    if gates_warn:
        checks.append(_check("quality_gates", "warn", "Gates de qualidade", "; ".join(gates_warn)))
    else:
        checks.append(_check("quality_gates", "ok", "Gates de qualidade", "thresholds dentro do recomendado"))

    statuses = {c["status"] for c in checks}
    final_status = "fail" if "fail" in statuses else ("warn" if "warn" in statuses else "ok")
    return {
        "status": final_status,
        "ready_for_scheduler_dry_run": final_status in {"ok", "warn"},
        "ready_for_real_send": False,
        "enabled": enabled,
        "dry_run": dry_run,
        "checks": checks,
        "summary": {
            "eligible_sources_count": len(eligible_source_keys),
            "eligible_sources": eligible_source_keys,
            "wishlists_opt_in": wishlists_opt_in,
            "recent_eligible_lots_with_bid": recent_with_bid,
            "scheduler_last_run_at": scheduler_last_run_at,
            "scheduler_last_status": scheduler_last_status,
            "dry_run_samples": sample_count,
            "min_score": min_score,
            "max_lot_age_hours": max_lot_age_hours,
            "max_per_user_per_day": max_per_user_per_day,
            "max_per_wishlist": max_per_wishlist,
            "max_wishlists": max_wishlists,
        },
    }
