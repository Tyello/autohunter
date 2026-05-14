import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, Numeric, Text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin


class AuctionLot(TimestampMixin, Base):
    __tablename__ = "auction_lots"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("auction_events.id", ondelete="SET NULL"), nullable=True)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    external_id: Mapped[str] = mapped_column(Text, nullable=False)
    lot_number: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    title: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    thumbnail_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    item_type: Mapped[str] = mapped_column(Text, nullable=False, default="other")
    make: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    model: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    version: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    year: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    mileage_km: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    fuel_type: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    transmission: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    color: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    city: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    state: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    location: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    initial_bid: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 2), nullable=True)
    current_bid: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 2), nullable=True)
    bid_increment: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 2), nullable=True)
    total_bids: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="unknown")
    auction_start_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    auction_end_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    condition: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    document_type: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    condition_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    has_documentation: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    has_debts: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    image_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    images: Mapped[Optional[list[str]]] = mapped_column(ARRAY(Text), nullable=True)
    extras: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    raw_payload: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)

    event = relationship("AuctionEvent", back_populates="lots")

    __table_args__ = (
        Index("uq_auction_lots_source_external_id", "source", "external_id", unique=True),
        Index("ix_auction_lots_source_status", "source", "status"),
        Index("ix_auction_lots_auction_end_at", "auction_end_at"),
        Index("ix_auction_lots_make_model_year", "make", "model", "year"),
        Index("ix_auction_lots_item_type_status", "item_type", "status"),
        Index("ix_auction_lots_city_state", "city", "state"),
    )
