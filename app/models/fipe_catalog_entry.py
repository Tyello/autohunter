import uuid
from decimal import Decimal

from sqlalchemy import CheckConstraint, Index, Numeric, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class FipeCatalogEntry(TimestampMixin, Base):
    __tablename__ = "fipe_catalog_entries"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    reference_month: Mapped[str] = mapped_column(Text, nullable=False)
    vehicle_type: Mapped[str] = mapped_column(Text, nullable=False, default="car")
    brand_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    brand_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    model_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    model_name: Mapped[str] = mapped_column(Text, nullable=False)
    year_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    model_year: Mapped[int | None] = mapped_column(nullable=True)
    fuel: Mapped[str | None] = mapped_column(Text, nullable=True)
    fipe_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(Text, nullable=False, default="BRL")
    raw_payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    source: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "reference_month", "vehicle_type", "brand_code", "model_code", "year_code", "source", name="uq_fipe_catalog_entries_key"
        ),
        Index("ix_fipe_catalog_month_type", "reference_month", "vehicle_type"),
        Index("ix_fipe_catalog_brand_model_year", "brand_name", "model_name", "model_year"),
        Index("ix_fipe_catalog_fipe_code", "fipe_code"),
    )
