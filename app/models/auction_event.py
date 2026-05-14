import uuid
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import DateTime, ForeignKey, Index, Integer, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin


class AuctionEvent(TimestampMixin, Base):
    __tablename__ = "auction_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    external_id: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    event_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="unknown")
    city: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    state: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    auction_type: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    modality: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    auctioneer: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    organizer: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    total_lots: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    vehicle_lots: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    extras: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    raw_payload: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB, nullable=True)

    lots = relationship("AuctionLot", back_populates="event")

    __table_args__ = (
        Index("uq_auction_events_source_external_id", "source", "external_id", unique=True),
        Index("ix_auction_events_source_status", "source", "status"),
    )
