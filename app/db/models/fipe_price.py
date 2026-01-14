from sqlalchemy import Date, Numeric, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from datetime import date, datetime
import uuid

from app.db.base import Base

class FipePrice(Base):
    __tablename__ = "fipe_prices"
    __table_args__ = (
        UniqueConstraint(
            "brand", "model", "version", "year", "fuel", "reference_month",
            name="uq_fipe_reference"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    brand: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[str | None] = mapped_column(Text)
    year: Mapped[int]
    fuel: Mapped[str | None] = mapped_column(Text)

    price: Mapped[float] = mapped_column(Numeric, nullable=False)
    reference_month: Mapped[date] = mapped_column(Date, nullable=False)

    created_at: Mapped[datetime]
    updated_at: Mapped[datetime]
