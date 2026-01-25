from decimal import Decimal

from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import Text, Numeric
from sqlalchemy.dialects.postgresql import UUID
import uuid

from app.db.base import Base, TimestampMixin

class CarListing(TimestampMixin, Base):
    __tablename__ = "car_listings"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,  # ✅ gera UUID no app
    )
    source: Mapped[str] = mapped_column(Text, nullable=False)
    external_id: Mapped[str] = mapped_column(Text, nullable=False)

    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    thumbnail_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    currency: Mapped[str] = mapped_column(Text, nullable=False, default="BRL")

    location: Mapped[str | None] = mapped_column(Text, nullable=True)

    @property
    def listing_url(self) -> str | None:
        """Compat layer for the API schema.

        The FastAPI response schema exposes `listing_url`, while the DB column is `url`.
        Exposing this property prevents response validation errors.
        """
        return self.url
