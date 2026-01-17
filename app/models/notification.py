import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import Text, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID

from app.db.base import Base, TimestampMixin


class Notification(TimestampMixin, Base):
    __tablename__ = "notifications"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )

    wishlist_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("wishlists.id", ondelete="SET NULL"),
        nullable=True,
    )

    car_listing_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("car_listings.id", ondelete="CASCADE"),
        nullable=False,
    )

    status: Mapped[str] = mapped_column(Text, nullable=False, default="queued")  # queued|sent|failed|suppressed
    sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Motivo curto (ex: daily_limit_reached, no_chat_id, telegram_error)
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Mensagem detalhada (stacktrace/erro do provider etc.)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    user = relationship("User")
    wishlist = relationship("Wishlist")
    car_listing = relationship("CarListing")
