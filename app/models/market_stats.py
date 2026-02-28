from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import Text, Integer, Numeric, DateTime

from app.db.base import Base, TimestampMixin


class MarketStatsCohort(TimestampMixin, Base):
    """Daily market stats by cohort (make+model+year).

    make/model are stored normalized (lowercase) to avoid case-splitting cohorts.
    """

    __tablename__ = "market_stats_cohorts"

    make: Mapped[str] = mapped_column(Text, primary_key=True)
    model: Mapped[str] = mapped_column(Text, primary_key=True)
    year: Mapped[int] = mapped_column(Integer, primary_key=True)

    median_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    p25_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    p75_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    sample_size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    computed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
