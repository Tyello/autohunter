from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.auction_event import AuctionEvent
from app.models.auction_lot import AuctionLot


def upsert_event(db: Session, payload: dict[str, Any]) -> AuctionEvent:
    source = payload["source"]
    external_id = str(payload["external_id"])
    event = db.query(AuctionEvent).filter(AuctionEvent.source == source, AuctionEvent.external_id == external_id).first()
    if event is None:
        event = AuctionEvent(source=source, external_id=external_id)
        db.add(event)
    for k, v in payload.items():
        if hasattr(event, k) and k not in {"id"}:
            setattr(event, k, v)
    db.flush()
    return event


def upsert_lot(db: Session, payload: dict[str, Any]) -> tuple[AuctionLot, bool]:
    source = payload["source"]
    external_id = str(payload["external_id"])
    now = datetime.now(timezone.utc)
    lot = db.query(AuctionLot).filter(AuctionLot.source == source, AuctionLot.external_id == external_id).first()
    created = False
    if lot is None:
        lot = AuctionLot(source=source, external_id=external_id, first_seen_at=now, last_seen_at=now)
        db.add(lot)
        created = True
    for k, v in payload.items():
        if hasattr(lot, k) and k not in {"id", "first_seen_at"}:
            setattr(lot, k, v)
    lot.last_seen_at = now
    db.flush()
    return lot, created


def list_upcoming_lots(db: Session, limit: int = 20) -> list[AuctionLot]:
    now = datetime.now(timezone.utc)
    return db.query(AuctionLot).filter(AuctionLot.auction_end_at.isnot(None), AuctionLot.auction_end_at >= now).order_by(AuctionLot.auction_end_at.asc()).limit(limit).all()


def list_lots_by_source(db: Session, source: str, limit: int = 20) -> list[AuctionLot]:
    return db.query(AuctionLot).filter(AuctionLot.source == source).order_by(AuctionLot.updated_at.desc()).limit(limit).all()


def list_motorcycle_lots(db: Session, limit: int = 20) -> list[AuctionLot]:
    return db.query(AuctionLot).filter(AuctionLot.item_type == "motorcycle").order_by(AuctionLot.updated_at.desc()).limit(limit).all()


def get_auction_stats(db: Session) -> dict[str, Any]:
    total = db.query(func.count(AuctionLot.id)).scalar() or 0
    by_source = db.query(AuctionLot.source, func.count(AuctionLot.id)).group_by(AuctionLot.source).all()
    by_status = db.query(AuctionLot.status, func.count(AuctionLot.id)).group_by(AuctionLot.status).all()
    return {"total_lots": total, "by_source": dict(by_source), "by_status": dict(by_status)}
