from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.models.auction_lot import AuctionLot
from app.sources.auctions.registry import list_auction_sources, resolve_auction_source_alias
from app.services.auction_notification_settings_service import get_auction_notification_runtime_settings
from app.services.auction_source_categories_service import get_auction_allowed_item_types


def _has_text(column):
    return func.length(func.trim(func.coalesce(column, ""))) > 0


def _score(metrics: dict[str, Any]) -> int:
    total = int(metrics["total_lots"])
    if total <= 0:
        return 0

    def cov(key: str) -> float:
        return float(metrics.get(key, 0) or 0) / total

    score = 20
    score += 15 if cov("with_current_bid_count") >= 0.50 else 0
    score += 10 if cov("with_initial_bid_count") >= 0.30 else 0
    score += 15 if cov("with_year_count") >= 0.50 else 0
    score += 10 if cov("with_city_state_count") >= 0.30 else 0
    score += 15 if cov("with_auction_end_at_count") >= 0.30 else 0
    score += 10 if cov("with_url_count") >= 0.90 else 0
    score += 10 if int(metrics.get("open_or_live_count", 0) or 0) > 0 else 0
    score += 5 if cov("with_image_count") > 0.0 else 0
    if int(metrics.get("updated_last_24h",0) or 0) == 0 and total > 0:
        score = max(10, score - 30)
    return min(100, score)


def _label(score: int) -> str:
    if score == 0:
        return "sem dados"
    if score >= 80:
        return "boa"
    if score >= 50:
        return "promissora"
    return "fraca"


def _build_source_metrics(db: Session, source: str, now_utc: datetime, car_pilot_window_hours: int) -> dict[str, Any]:
    cutoff = now_utc - timedelta(hours=24)
    car_pilot_cutoff = now_utc - timedelta(hours=car_pilot_window_hours if car_pilot_window_hours > 0 else 48)
    total_lots = int(db.query(func.count(AuctionLot.id)).filter(AuctionLot.source == source).scalar() or 0)
    updated_last_24h = int(
        db.query(func.count(AuctionLot.id)).filter(AuctionLot.source == source, AuctionLot.updated_at >= cutoff).scalar() or 0
    )
    latest_updated_at = db.query(func.max(AuctionLot.updated_at)).filter(AuctionLot.source == source).scalar()

    status_counts = {
        (k or "unknown"): int(v)
        for k, v in db.query(AuctionLot.status, func.count(AuctionLot.id)).filter(AuctionLot.source == source).group_by(AuctionLot.status).all()
    }
    item_type_counts = {
        (k or "other"): int(v)
        for k, v in db.query(AuctionLot.item_type, func.count(AuctionLot.id)).filter(AuctionLot.source == source).group_by(AuctionLot.item_type).all()
    }

    with_title_count = int(db.query(func.count(AuctionLot.id)).filter(AuctionLot.source == source, _has_text(AuctionLot.title)).scalar() or 0)
    with_year_count = int(db.query(func.count(AuctionLot.id)).filter(AuctionLot.source == source, AuctionLot.year.isnot(None)).scalar() or 0)
    with_current_bid_count = int(db.query(func.count(AuctionLot.id)).filter(AuctionLot.source == source, AuctionLot.current_bid.isnot(None)).scalar() or 0)
    with_initial_bid_count = int(db.query(func.count(AuctionLot.id)).filter(AuctionLot.source == source, AuctionLot.initial_bid.isnot(None)).scalar() or 0)
    with_auction_end_at_count = int(db.query(func.count(AuctionLot.id)).filter(AuctionLot.source == source, AuctionLot.auction_end_at.isnot(None)).scalar() or 0)
    with_city_state_count = int(
        db.query(func.count(AuctionLot.id)).filter(AuctionLot.source == source, _has_text(AuctionLot.city), _has_text(AuctionLot.state)).scalar() or 0
    )
    with_url_count = int(db.query(func.count(AuctionLot.id)).filter(AuctionLot.source == source, _has_text(AuctionLot.url)).scalar() or 0)
    with_image_count = int(
        db.query(func.count(AuctionLot.id))
        .filter(
            AuctionLot.source == source,
            (AuctionLot.image_count.isnot(None) & (AuctionLot.image_count > 0))
            | _has_text(AuctionLot.thumbnail_url),
        )
        .scalar()
        or 0
    )
    allowed_item_types = get_auction_allowed_item_types(db, source)
    car_lots = int(db.query(func.count(AuctionLot.id)).filter(AuctionLot.source == source, AuctionLot.item_type == "car").scalar() or 0)
    user_allowed_lots = 0
    if allowed_item_types:
        user_allowed_lots = int(
            db.query(func.count(AuctionLot.id))
            .filter(AuctionLot.source == source, AuctionLot.item_type.in_(sorted(allowed_item_types)))
            .scalar()
            or 0
        )
    source_ready_for_user_car_pilot = bool(
        db.query(func.count(AuctionLot.id))
        .filter(
            AuctionLot.source == source,
            AuctionLot.item_type == "car",
            AuctionLot.updated_at >= car_pilot_cutoff,
            _has_text(AuctionLot.url),
            AuctionLot.year.isnot(None),
            or_(AuctionLot.current_bid.isnot(None), AuctionLot.initial_bid.isnot(None)),
        )
        .scalar()
        or 0
    )

    upcoming_count = int(db.query(func.count(AuctionLot.id)).filter(AuctionLot.source == source, AuctionLot.auction_end_at > now_utc).scalar() or 0)
    open_or_live_count = int(
        db.query(func.count(AuctionLot.id))
        .filter(AuctionLot.source == source, func.lower(func.coalesce(AuctionLot.status, "")).in_(["open", "live"]))
        .scalar()
        or 0
    )
    ended_count = int(
        db.query(func.count(AuctionLot.id))
        .filter(AuctionLot.source == source, (func.lower(func.coalesce(AuctionLot.status, "")) == "ended") | (AuctionLot.auction_end_at <= now_utc))
        .scalar()
        or 0
    )

    metrics: dict[str, Any] = {
        "source": source,
        "total_lots": total_lots,
        "updated_last_24h": updated_last_24h,
        "latest_updated_at": latest_updated_at,
        "status_counts": status_counts,
        "item_type_counts": item_type_counts,
        "with_title_count": with_title_count,
        "with_year_count": with_year_count,
        "with_current_bid_count": with_current_bid_count,
        "with_initial_bid_count": with_initial_bid_count,
        "with_auction_end_at_count": with_auction_end_at_count,
        "with_city_state_count": with_city_state_count,
        "with_url_count": with_url_count,
        "with_image_count": with_image_count,
        "car_lots": car_lots,
        "user_allowed_lots": user_allowed_lots,
        "source_ready_for_user_car_pilot": source_ready_for_user_car_pilot,
        "car_pilot_window_hours": car_pilot_window_hours if car_pilot_window_hours > 0 else 48,
        "upcoming_count": upcoming_count,
        "open_or_live_count": open_or_live_count,
        "ended_count": ended_count,
    }
    metrics["quality_score"] = _score(metrics)
    metrics["quality_label"] = "sem dados recentes" if (metrics["total_lots"] > 0 and metrics["updated_last_24h"] == 0) else _label(metrics["quality_score"])
    metrics["stale_warning"] = "Dados sem atualização recente; execute run/inspect antes de avaliar." if metrics["updated_last_24h"] == 0 and metrics["total_lots"] > 0 else None
    return metrics


def build_auction_quality_report(db: Session, source: str | None = None) -> dict[str, Any]:
    now_utc = datetime.now(timezone.utc)
    keys = [item.key for item in list_auction_sources()]
    if source:
        key = resolve_auction_source_alias(source)
        if key:
            keys = [key]
        elif source in keys:
            keys = [source]
        else:
            keys = []

    cfg = get_auction_notification_runtime_settings(db)
    car_pilot_window_hours = int(cfg.get("max_lot_age_hours") or 48)

    sources = [_build_source_metrics(db, key, now_utc, car_pilot_window_hours) for key in keys]
    return {"generated_at": now_utc, "sources": sources, "car_pilot_window_hours": car_pilot_window_hours}
