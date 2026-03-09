from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, Optional

from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import Text, Numeric, Integer, Boolean, DateTime
from sqlalchemy.dialects.postgresql import UUID, JSONB

from app.db.base import Base, TimestampMixin


class CarListing(TimestampMixin, Base):
    """Normalized automotive listing.

    The DB schema has been extended over time (fase1_002_car_listings) to include
    common fields (year/make/model/etc) and extensibility (extras/raw_payload).

    Keep this model aligned with the DB so bulk upserts can persist those fields.
    """

    __tablename__ = "car_listings"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    # Dedup
    source: Mapped[str] = mapped_column(Text, nullable=False)
    external_id: Mapped[str] = mapped_column(Text, nullable=False)

    # Core fields
    title: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    thumbnail_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    price: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2), nullable=True)
    currency: Mapped[str] = mapped_column(Text, nullable=False, default="BRL")
    location: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Extensible / debug
    extras: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    raw_payload: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    listing_type: Mapped[str] = mapped_column(Text, nullable=False, default="marketplace")
    extractor_version: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Promoted common fields
    year: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    mileage_km: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    fuel_type: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    transmission: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    make: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    model: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    version: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    seller_type: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    city: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    state: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    color: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Marketplace lifecycle
    is_sold: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    sold_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    @property
    def listing_url(self) -> str | None:
        """Compat layer for API schema.

        FastAPI response uses `listing_url` while DB column is `url`.
        """
        return self.url
