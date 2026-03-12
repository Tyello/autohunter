from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class WishlistListingActivity(TimestampMixin, Base):
    """Persistent activity state for listing lifecycle per wishlist.

    Tracks whether a listing is currently active in a wishlist monitoring view,
    allowing conservative inactivation (after N valid missing runs) and
    reactivation when it appears again.
    """

    __tablename__ = "wishlist_listing_activity"

    __table_args__ = (
        UniqueConstraint("wishlist_id", "listing_identity_key", name="uq_wishlist_listing_activity_wishlist_identity"),
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

    last_valid_run_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("source_runs.id", ondelete="SET NULL"),
        nullable=True,
    )

    listing_identity_key: Mapped[str] = mapped_column(Text, nullable=False)
    source_name: Mapped[str] = mapped_column(Text, nullable=False)
    source_listing_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    listing_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    status: Mapped[str] = mapped_column(Text, nullable=False, default="active")  # active|inactive
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    missing_runs_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    inactive_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    inactive_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    reactivated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
