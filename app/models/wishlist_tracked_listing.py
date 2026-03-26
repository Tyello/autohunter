from __future__ import annotations

import uuid

from typing import Optional

from sqlalchemy import CheckConstraint, ForeignKey, Integer, UniqueConstraint
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
