import uuid
from decimal import Decimal

from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import Text, Numeric
from sqlalchemy.dialects.postgresql import UUID

from app.db.base import Base, TimestampMixin


class FipePrice(TimestampMixin, Base):
    __tablename__ = "fipe_prices"

    # PK
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    # Identificador simples do veículo no MVP (ex: "Honda Civic 2019 Touring")
    vehicle_key: Mapped[str] = mapped_column(Text, nullable=False)

    # Valor FIPE
    fipe_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)

    currency: Mapped[str] = mapped_column(Text, nullable=False, default="BRL")

    # Competência (ex: "2026-01")
    reference_month: Mapped[str] = mapped_column(Text, nullable=False)

    # Constraint do schema (deve bater com migration)
    __table_args__ = (
        # vehicle_key + reference_month únicos (uma FIPE por competência)
        {"sqlite_autoincrement": True},
    )
