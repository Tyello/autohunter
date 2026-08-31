from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.auction_event import AuctionEvent
from app.models.auction_lot import AuctionLot


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
