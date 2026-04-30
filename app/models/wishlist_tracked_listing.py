from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from typing import Optional

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, Numeric, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class WishlistTrackedListing(TimestampMixin, Base):
    """User-selected listings tracked under a wishlist (max 3 rows per wishlist)."""

    __tablename__ = "wishlist_tracked_listings"

    __table_args__ = (
        UniqueConstraint("wishlist_id", "car_listing_id", name="uq_wishlist_tracked_listing_pair"),
        UniqueConstraint("wishlist_id", "slot", name="uq_wishlist_tracked_listing_slot"),
        CheckConstraint("slot >= 1 AND slot <= 3", name="ck_wishlist_tracked_listing_slot_range"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    wishlist_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("wishlists.id", ondelete="RESTRICT"),
        nullable=False,
    )

    car_listing_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("car_listings.id", ondelete="SET NULL"),
        nullable=True,
    )

    slot: Mapped[int] = mapped_column(Integer, nullable=False)
    initial_price: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2), nullable=True)
    last_observed_price: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2), nullable=True)
    last_price_change_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2), nullable=True)
    last_price_change_pct: Mapped[Optional[Decimal]] = mapped_column(Numeric(7, 4), nullable=True)
    last_price_change_direction: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    last_price_change_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_seen_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    listing_status: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
