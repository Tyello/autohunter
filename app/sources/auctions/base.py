from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any


@dataclass(slots=True)
class NormalizedAuctionLot:
    source: str
    external_id: str
    url: str | None = None
    title: str | None = None
    lot_number: str | None = None
    item_type: str = "other"
    make: str | None = None
    model: str | None = None
    version: str | None = None
    year: int | None = None
    mileage_km: int | None = None
    city: str | None = None
    state: str | None = None
    location: str | None = None
    initial_bid: Decimal | None = None
    current_bid: Decimal | None = None
    bid_increment: Decimal | None = None
    total_bids: int | None = None
    status: str = "unknown"
    auction_start_at: datetime | None = None
    auction_end_at: datetime | None = None
    condition: str | None = None
    document_type: str | None = None
    thumbnail_url: str | None = None
    images: list[str] | None = None
    extras: dict[str, Any] = field(default_factory=dict)
    raw_payload: dict[str, Any] = field(default_factory=dict)

    def to_payload(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "external_id": self.external_id,
            "url": self.url,
            "title": self.title,
            "lot_number": self.lot_number,
            "item_type": self.item_type,
            "make": self.make,
            "model": self.model,
            "version": self.version,
            "year": self.year,
            "mileage_km": self.mileage_km,
            "city": self.city,
            "state": self.state,
            "location": self.location,
            "initial_bid": self.initial_bid,
            "current_bid": self.current_bid,
            "bid_increment": self.bid_increment,
            "total_bids": self.total_bids,
            "status": self.status,
            "auction_start_at": self.auction_start_at,
            "auction_end_at": self.auction_end_at,
            "condition": self.condition,
            "document_type": self.document_type,
            "thumbnail_url": self.thumbnail_url,
            "images": self.images,
            "image_count": len(self.images) if self.images else None,
            "extras": self.extras,
            "raw_payload": self.raw_payload,
        }
